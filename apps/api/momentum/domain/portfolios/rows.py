"""Phase 7.5 (spec §5.3): a portfolio's rows, as the viewer sees them, with every built-in column
computed in SQL. One query per column family over all the rows at once (never one per project),
so the query count stays the same however many projects the portfolio holds.

A view (saved or ad hoc) adds filters, grouping and sort, all applied here on the server. Hidden
projects (in the portfolio, not visible to the viewer) are only counted, never named.
"""

from __future__ import annotations

import contextlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, and_, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.access import project_roles, visible_projects_clause
from momentum.domain.fields.models import FieldDef, FieldValue, ProjectFieldEvent, ProjectFieldValue
from momentum.domain.forecasts.models import Forecast
from momentum.domain.portfolios.membership import condition_clause, members_clause
from momentum.domain.portfolios.models import Portfolio, PortfolioItem
from momentum.domain.projects.models import Project
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject
from momentum.domain.tasks.service import local_date_for, today_for
from momentum.domain.users.models import User

# spec §5.2: the built-in column keys, in their default order
BUILTIN_COLUMNS = (
    "name",
    "owner",
    "status",
    "stage",
    "progress",
    "open",
    "overdue",
    "blocked",
    "waiting_on_customer",
    "next_milestone",
    "target_date",
    "forecast_date",
    "slip_days",
    "stage_age_days",
    "latest_update",
)
COLUMN_LABELS = {
    "name": "Project",
    "owner": "Owner",
    "status": "Health",
    "stage": "Stage",
    "progress": "Progress",
    "open": "Open",
    "overdue": "Overdue",
    "blocked": "Blocked",
    "waiting_on_customer": "Waiting on customer",
    "next_milestone": "Next milestone",
    "target_date": "Target date",
    "forecast_date": "Forecast (P80)",
    "slip_days": "Slip (days)",
    "stage_age_days": "Days in stage",
    "latest_update": "Latest update",
}
# worst first, as the S6.2.2 rollup reads health
SEVERITY = ("off_track", "at_risk", "on_hold", "on_track", "complete")
GROUPABLE = ("status", "owner", "stage")
WAITING_FIELD = "waiting on"
WAITING_OPTION = "customer"
NUMERIC = ("number", "currency", "percent")


@dataclass
class ViewSpec:
    """Filters, grouping and sort (a saved view's, or ad hoc ones from the request)."""

    filters: dict[str, Any] = field(default_factory=dict)
    group_by: str | None = None
    sort: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Group:
    key: str | None
    label: str
    project_ids: list[uuid.UUID]
    rollup: dict[str, Any]


@dataclass
class Rows:
    rows: list[dict[str, Any]]
    hidden: int
    groups: list[Group] | None
    fields: list[FieldDef]


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v))
    except ValueError:
        return None


def column_key_ok(key: str, fields: dict[uuid.UUID, FieldDef]) -> bool:
    if key in BUILTIN_COLUMNS:
        return True
    if key.startswith("field:"):
        fid = _uuid(key.removeprefix("field:"))
        return fid is not None and fid in fields
    return False


def _member_query(ctx: Ctx, p: Portfolio, spec: ViewSpec) -> Select[tuple[Project]]:
    q = select(Project).where(members_clause(p), visible_projects_clause(ctx))
    if p.kind == "manual":
        q = q.join(
            PortfolioItem,
            and_(PortfolioItem.project_id == Project.id, PortfolioItem.portfolio_id == p.id),
        )
        q = q.order_by(PortfolioItem.position)
    else:
        q = q.order_by(func.lower(Project.name), Project.id)
    f = spec.filters or {}
    if f.get("q"):
        text = str(f["q"]).strip()
        if text:
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q = q.where(Project.name.ilike(f"%{escaped}%", escape="\\"))
    statuses = [s for s in f.get("status") or [] if s in SEVERITY or s == "none"]
    if statuses:
        named = [s for s in statuses if s != "none"]
        q = q.where(
            or_(
                Project.status.in_(named) if named else literal(False),
                Project.status.is_(None) if "none" in statuses else literal(False),
            )
        )
    owners = [o for o in (_uuid(v) for v in f.get("owner_ids") or []) if o is not None]
    if owners:
        q = q.where(Project.owner_id.in_(owners))
    stages = [str(s) for s in f.get("stage") or []]
    if stages and p.stage_field_id is not None:
        q = q.where(
            condition_clause({"field_id": str(p.stage_field_id), "op": "any", "value": stages})
        )
    for cond in f.get("fields") or []:
        if isinstance(cond, dict):
            q = q.where(condition_clause(cond))
    return q


async def visible_member_ids(session: AsyncSession, ctx: Ctx, p: Portfolio) -> list[uuid.UUID]:
    """The portfolio's projects the viewer can see (the workload grid's scope)."""
    rows = await session.execute(
        select(Project.id).where(members_clause(p), visible_projects_clause(ctx))
    )
    return list(rows.scalars())


async def _hidden(session: AsyncSession, ctx: Ctx, p: Portfolio) -> int:
    total = (
        await session.execute(select(func.count()).select_from(Project).where(members_clause(p)))
    ).scalar_one()
    seen = (
        await session.execute(
            select(func.count())
            .select_from(Project)
            .where(members_clause(p), visible_projects_clause(ctx))
        )
    ).scalar_one()
    return int(total) - int(seen)


def _label(f: FieldDef | None, option_id: Any) -> str | None:
    for o in (f.options if f is not None else None) or []:
        if isinstance(o, dict) and o.get("id") == option_id:
            return str(o.get("label"))
    return None


def _option_order(f: FieldDef | None) -> list[str]:
    return [
        str(o["id"]) for o in (f.options if f is not None else None) or [] if isinstance(o, dict)
    ]


async def portfolio_rows_v2(
    session: AsyncSession,
    ctx: Ctx,
    p: Portfolio,
    spec: ViewSpec | None = None,
    *,
    today: date | None = None,
) -> Rows:
    spec = spec or ViewSpec()
    today = today or today_for(ctx)  # the viewer's day, as reports and dashboards (H66)
    projects = list((await session.execute(_member_query(ctx, p, spec))).scalars())
    hidden = await _hidden(session, ctx, p)
    defs = list(
        (
            await session.execute(
                select(FieldDef)
                .where(
                    FieldDef.workspace_id == ctx.workspace_id,
                    FieldDef.applies_to == "project",
                    FieldDef.deleted_at.is_(None),
                )
                .order_by(FieldDef.name)
            )
        ).scalars()
    )
    by_id = {f.id: f for f in defs}
    stage_field = by_id.get(p.stage_field_id) if p.stage_field_id else None
    ids = [x.id for x in projects]
    if not ids:
        return Rows([], hidden, [] if spec.group_by else None, defs)

    rows = await compute_rows(
        session,
        ctx,
        projects,
        stage_field=stage_field,
        stage_targets=p.stage_targets or {},
        columns=p.columns or [],
        today=today,
        live_fields=set(by_id),
    )
    if (spec.filters or {}).get("overdue_only"):
        rows = [r for r in rows if r["overdue"]]
    rows = _sorted(rows, spec.sort, by_id, stage_field)
    groups = _grouped(rows, spec.group_by, by_id, stage_field) if spec.group_by else None
    return Rows(rows, hidden, groups, defs)


def sort_value(row: dict[str, Any], key: str, stage_field: FieldDef | None) -> Any:
    if key == "owner":
        return (row["owner_name"] or "").lower() or None
    if key == "status":
        return SEVERITY.index(row["status"]) if row["status"] in SEVERITY else None
    if key == "stage":
        order = _option_order(stage_field)
        st = row["stage"]
        return order.index(st["option_id"]) if st and st["option_id"] in order else None
    if key == "next_milestone":
        m = row["next_milestone"]
        return m["due_on"] if m else None
    if key == "latest_update":
        u = row["latest_update"]
        return u["at"] if u else None
    if key == "name":
        return row["name"].lower()
    if key.startswith("field:"):
        v = row["fields"].get(key.removeprefix("field:"))
        return v if isinstance(v, int | float | str) and not isinstance(v, bool) else None
    if key == "open":
        return row["open"]
    if key == "overdue":
        return row["overdue"]
    return row.get(key)


def _sorted(
    rows: list[dict[str, Any]],
    sort: list[dict[str, Any]],
    fields: dict[uuid.UUID, FieldDef],
    stage_field: FieldDef | None,
) -> list[dict[str, Any]]:
    for s in reversed(sort or []):
        key = str(s.get("key", ""))
        if not column_key_ok(key, fields):
            raise ValidationFailed(f"Can't sort by {key}", code="invalid_sort")
        desc = s.get("dir") == "desc"
        present = [r for r in rows if sort_value(r, key, stage_field) is not None]
        missing = [r for r in rows if sort_value(r, key, stage_field) is None]
        present.sort(key=lambda r: sort_value(r, key, stage_field), reverse=desc)
        rows = present + missing  # empty values last, whichever direction
    return rows


def _rollup(rows: list[dict[str, Any]], fields: dict[uuid.UUID, FieldDef]) -> dict[str, Any]:
    progress = [r["progress"] for r in rows if r["progress"] is not None]
    sums: dict[str, float] = {}
    avgs: dict[str, float] = {}
    for fid, f in fields.items():
        if f.type not in NUMERIC:
            continue
        nums = [
            r["fields"][str(fid)]
            for r in rows
            if isinstance(r["fields"].get(str(fid)), int | float)
            and not isinstance(r["fields"].get(str(fid)), bool)
        ]
        if nums:
            sums[str(fid)] = sum(nums)
            avgs[str(fid)] = round(sum(nums) / len(nums), 4)
    return {
        "count": len(rows),
        "progress_avg": round(sum(progress) / len(progress), 4) if progress else None,
        "overdue_total": sum(r["overdue"] for r in rows),
        "sums": sums,
        "avgs": avgs,
    }


def _grouped(
    rows: list[dict[str, Any]],
    group_by: str,
    fields: dict[uuid.UUID, FieldDef],
    stage_field: FieldDef | None,
) -> list[Group]:
    buckets: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    order: list[str | None]
    labels: dict[str | None, str] = {None: "None"}
    if group_by == "status":
        for r in rows:
            buckets[r["status"]].append(r)
        order = [*SEVERITY, None]
        labels.update({s: s.replace("_", " ").capitalize() for s in SEVERITY})
        labels[None] = "No status"
    elif group_by == "owner":
        for r in rows:
            buckets[str(r["owner_id"]) if r["owner_id"] else None].append(r)
            if r["owner_id"]:
                labels[str(r["owner_id"])] = r["owner_name"] or "Unknown"
        order = [*sorted((k for k in buckets if k), key=lambda k: labels[k].lower()), None]
        labels[None] = "No owner"
    elif group_by == "stage" or group_by.startswith("field:"):
        f = (
            stage_field
            if group_by == "stage"
            else fields.get(_uuid(group_by.removeprefix("field:")) or uuid.UUID(int=0))
        )
        if f is None or f.type not in ("single_select", "checkbox", "text"):
            raise ValidationFailed(f"Can't group by {group_by}", code="invalid_group")
        fid = str(f.id)
        for r in rows:
            v = r["fields"].get(fid)
            buckets[str(v) if v is not None else None].append(r)
        if f.type == "single_select":
            order = [*_option_order(f), None]
            labels.update({k: _label(f, k) or k for k in order if k})
        else:
            order = [*sorted(k for k in buckets if k is not None), None]
            labels.update({k: k for k in order if k})
        labels[None] = f"No {f.name}"
    else:
        raise ValidationFailed(f"Can't group by {group_by}", code="invalid_group")
    out = []
    for k in order:
        members = buckets.get(k, [])
        if k is not None or members:  # every stage shows, even empty; "None" only when used
            out.append(
                Group(
                    k, labels.get(k, str(k)), [r["id"] for r in members], _rollup(members, fields)
                )
            )
    return out


async def compute_rows(
    session: AsyncSession,
    ctx: Ctx,
    projects: list[Project],
    *,
    stage_field: FieldDef | None,
    stage_targets: dict[str, Any],
    columns: list[dict[str, Any]],
    today: date,
    live_fields: set[uuid.UUID],
) -> list[dict[str, Any]]:
    """Every built-in column for these projects (already visible to the viewer), one SQL query
    per column family. Shared by portfolio rows and dashboard ``projects`` queries (S75-08)."""
    ids = [x.id for x in projects]
    if not ids:
        return []
    by_id = dict.fromkeys(live_fields)
    counts: dict[uuid.UUID, tuple[int, int, int]] = {}
    for pid, total, done, overdue in (
        await session.execute(
            select(
                TaskProject.project_id,
                func.count(),
                func.count(Task.completed_at),
                func.count().filter(Task.completed_at.is_(None), Task.due_on < today),
            )
            .join(Task, Task.id == TaskProject.task_id)
            .where(
                TaskProject.project_id.in_(ids),
                Task.parent_id.is_(None),
                Task.deleted_at.is_(None),
            )
            .group_by(TaskProject.project_id)
        )
    ).all():
        counts[pid] = (int(total), int(done), int(overdue))

    # blocked: open tasks (any depth) with at least one open, live blocker
    blocker = Task.__table__.alias("blocker")
    blocked = {
        pid: int(n)
        for pid, n in (
            await session.execute(
                select(TaskProject.project_id, func.count(func.distinct(Task.id)))
                .join(Task, Task.id == TaskProject.task_id)
                .join(TaskDependency, TaskDependency.task_id == Task.id)
                .join(blocker, blocker.c.id == TaskDependency.depends_on_id)
                .where(
                    TaskProject.project_id.in_(ids),
                    Task.deleted_at.is_(None),
                    Task.completed_at.is_(None),
                    blocker.c.deleted_at.is_(None),
                    blocker.c.completed_at.is_(None),
                )
                .group_by(TaskProject.project_id)
            )
        ).all()
    }

    # waiting on customer: the task field "Waiting on" = "Customer", matched by name and label
    # (a portfolio may name another field and choice in its waiting_on_customer column)
    meta = next((c for c in columns or [] if c.get("key") == "waiting_on_customer"), {})
    waiting_field = str(meta.get("field_name") or WAITING_FIELD).strip().lower()
    waiting_option = str(meta.get("option_label") or WAITING_OPTION).strip().lower()
    waiting_pairs = [
        (f.id, str(o["id"]))
        for f in (
            await session.execute(
                select(FieldDef).where(
                    FieldDef.workspace_id == ctx.workspace_id,
                    FieldDef.applies_to == "task",
                    FieldDef.deleted_at.is_(None),
                    func.lower(FieldDef.name) == waiting_field,
                )
            )
        ).scalars()
        for o in f.options or []
        if isinstance(o, dict) and str(o.get("label", "")).strip().lower() == waiting_option
    ]
    waiting: dict[uuid.UUID, int] = {}
    if waiting_pairs:
        match = or_(
            *(
                and_(
                    FieldValue.field_id == fid,
                    FieldValue.value == cast(literal(f'"{oid}"'), JSONB),
                )
                for fid, oid in waiting_pairs
            )
        )
        waiting = {
            pid: int(n)
            for pid, n in (
                await session.execute(
                    select(TaskProject.project_id, func.count(func.distinct(Task.id)))
                    .join(Task, Task.id == TaskProject.task_id)
                    .join(FieldValue, FieldValue.task_id == Task.id)
                    .where(
                        TaskProject.project_id.in_(ids),
                        Task.deleted_at.is_(None),
                        Task.completed_at.is_(None),
                        match,
                    )
                    .group_by(TaskProject.project_id)
                )
            ).all()
        }

    milestones: dict[uuid.UUID, dict[str, Any]] = {}
    for pid, tid, title, due in (
        await session.execute(
            select(TaskProject.project_id, Task.id, Task.title, Task.due_on)
            .join(Task, Task.id == TaskProject.task_id)
            .where(
                TaskProject.project_id.in_(ids),
                Task.type == "milestone",
                Task.deleted_at.is_(None),
                Task.completed_at.is_(None),
            )
            .distinct(TaskProject.project_id)
            .order_by(TaskProject.project_id, Task.due_on.asc().nulls_last(), Task.title)
        )
    ).all():
        milestones[pid] = {"id": tid, "title": title, "due_on": due}

    # the go-live target a slip is measured against (H69): the "Target go-live" date field
    golive = (
        await session.execute(
            select(FieldDef.id).where(
                FieldDef.workspace_id == ctx.workspace_id,
                FieldDef.applies_to == "project",
                FieldDef.type == "date",
                FieldDef.deleted_at.is_(None),
                func.lower(FieldDef.name) == "target go-live",
            )
        )
    ).scalar()
    golive_on: dict[uuid.UUID, date] = {}
    values: dict[uuid.UUID, dict[str, Any]] = defaultdict(dict)
    for pid, fid, value in (
        await session.execute(
            select(
                ProjectFieldValue.project_id, ProjectFieldValue.field_id, ProjectFieldValue.value
            ).where(ProjectFieldValue.project_id.in_(ids))
        )
    ).all():
        if fid in by_id:
            values[pid][str(fid)] = value
        if fid == golive and isinstance(value, str):
            with contextlib.suppress(ValueError):
                golive_on[pid] = date.fromisoformat(value[:10])

    entered: dict[uuid.UUID, datetime] = {}
    if stage_field is not None:
        for pid, at in (
            await session.execute(
                select(ProjectFieldEvent.project_id, func.max(ProjectFieldEvent.at))
                .where(
                    ProjectFieldEvent.project_id.in_(ids),
                    ProjectFieldEvent.field_id == stage_field.id,
                )
                .group_by(ProjectFieldEvent.project_id)
            )
        ).all():
            entered[pid] = at

    forecasts: dict[uuid.UUID, date | None] = {
        pid: p80
        for pid, p80 in (
            await session.execute(
                select(Forecast.project_id, Forecast.p80)
                .where(Forecast.project_id.in_(ids))
                .distinct(Forecast.project_id)
                .order_by(Forecast.project_id, Forecast.computed_at.desc())
            )
        ).all()
    }

    updates: dict[uuid.UUID, dict[str, Any]] = {}
    for pid, title, at, status in (
        await session.execute(
            select(
                StatusUpdate.entity_id,
                StatusUpdate.title,
                StatusUpdate.created_at,
                StatusUpdate.status,
            )
            .where(
                StatusUpdate.entity_type == "project",
                StatusUpdate.entity_id.in_(ids),
                StatusUpdate.deleted_at.is_(None),
            )
            .distinct(StatusUpdate.entity_id)
            .order_by(StatusUpdate.entity_id, StatusUpdate.created_at.desc())
        )
    ).all():
        updates[pid] = {"title": title, "at": at, "status": status}

    owner_ids = {x.owner_id for x in projects if x.owner_id}
    owners = (
        {
            u.id: u.name
            for u in (await session.execute(select(User).where(User.id.in_(owner_ids)))).scalars()
        }
        if owner_ids
        else {}
    )

    roles = await project_roles(session, ctx, projects)
    rows: list[dict[str, Any]] = []
    targets = stage_targets or {}
    for x in projects:
        total, done, overdue = counts.get(x.id, (0, 0, 0))
        fields = values.get(x.id, {})
        stage_value = fields.get(str(stage_field.id)) if stage_field else None
        entered_at = entered.get(x.id)
        since = local_date_for(ctx, entered_at) if entered_at else None
        stage_age = (today - since).days if since and stage_value else None
        target_days = targets.get(str(stage_value)) if stage_value is not None else None
        # the project's go-live target, never the end of its current stage (H69): a stage's
        # lateness is stage age vs stage target; the slip compares the go-live forecast with this
        target: date | None = golive_on.get(x.id) or x.due_on
        forecast = forecasts.get(x.id)
        rows.append(
            {
                "id": x.id,
                "name": x.name,
                "color": x.color,
                "owner_id": x.owner_id,
                "owner_name": owners.get(x.owner_id) if x.owner_id else None,
                "status": x.status,
                "template_id": x.template_id,
                "start_on": x.start_on,
                "due_on": x.due_on,
                "total_tasks": total,
                "completed_tasks": done,
                "open": total - done,
                "overdue": overdue,
                "progress": round(done / total, 4) if total else None,
                "blocked": blocked.get(x.id, 0),
                "waiting_on_customer": waiting.get(x.id, 0) if waiting_pairs else None,
                "next_milestone": milestones.get(x.id),
                "stage": (
                    {"option_id": stage_value, "label": _label(stage_field, stage_value)}
                    if stage_value is not None
                    else None
                ),
                "stage_age_days": stage_age,
                "stage_target_days": int(target_days)
                if isinstance(target_days, int | float)
                else None,
                "target_date": target,
                "forecast_date": forecast,
                "slip_days": (forecast - target).days if forecast and target else None,
                "latest_update": updates.get(x.id),
                "fields": fields,
                "can_edit": roles.get(x.id) in ("admin", "editor"),
            }
        )

    return rows
