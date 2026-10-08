"""Phase 7.5 (spec §7.1-§7.3, §7.6): one entry point for every widget spec, v1 or v2.

``run_any`` sends a spec to its entity's module (``query.py`` for v1 tasks, ``query_tasks``,
``query_projects``, ``query_stages``, ``query_snapshots``), after applying the dashboard filters:

- ``portfolio_id`` replaces the widget's portfolio (tasks, projects, stage events, snapshots);
- ``owner`` (``"me"`` allowed) narrows to projects those people own;
- ``assignee`` replaces a tasks widget's assignees;
- ``fields`` (project-field conditions) narrow the projects;
- ``period`` replaces the widget's window (a series' ``window_days``, a "completed in the last N
  days" filter, a stage analysis' window). A custom period counts its length back from today.

A v1 spec with no filters to apply runs exactly as before (``query.run``); with filters it runs as
the equivalent v2 tasks spec. A filter an entity can't take is left out and said in ``notes``.

``check_any`` is what the models can't check alone: the fields a spec names exist and suit their
use, and its portfolio is one the viewer can see.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.dashboards import query
from momentum.domain.dashboards.query_projects import (
    drill_projects,
    project_rows,
    run_projects,
)
from momentum.domain.dashboards.query_scope import (
    now_utc,
    period_bounds,
    period_window,
    scope_projects,
)
from momentum.domain.dashboards.query_snapshots import drill_snapshots, run_snapshots
from momentum.domain.dashboards.query_stages import drill_stage, run_stages
from momentum.domain.dashboards.query_tasks import drill_tasks, run_tasks
from momentum.domain.dashboards.schemas import (
    DrillAnyIn,
    DrillIn,
    DrillOut,
    DrillProjectOut,
    QueryResultOut,
    QuerySpec,
)
from momentum.domain.dashboards.schemas_v2 import (
    DashboardFilters,
    NoteSpec,
    ProjectsSpec,
    SnapshotSpec,
    StageSpec,
    TasksSpec,
)
from momentum.domain.fields.filters import NUMERIC
from momentum.domain.fields.models import FieldDef
from momentum.domain.portfolios.service import get_portfolio
from momentum.domain.projects.models import Project
from momentum.domain.users.models import User

PROJECT_GROUPABLE = ("single_select", "people", "checkbox")


def has_filters(f: DashboardFilters | None) -> bool:
    return f is not None and bool(f.portfolio_id or f.period or f.owner or f.assignee or f.fields)


def upcast(spec: QuerySpec) -> TasksSpec:
    """A v1 spec as the same question in v2 (so dashboard filters can apply to it)."""
    data = spec.model_dump(mode="json", exclude={"version", "entity"})
    return TasksSpec.model_validate({**data, "version": 2, "entity": "tasks"})


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


class Applied:
    """A spec with the dashboard filters applied, plus what the tasks runner narrows by."""

    def __init__(self, spec: Any) -> None:
        self.spec = spec
        self.owner: list[str] = []
        self.fields: list[dict[str, Any]] = []
        self.window: int | None = None
        self.period: str | None = None  # a calendar period (not custom)
        self.prev_len: int | None = None  # its previous period's length, in days
        self.notes: list[str] = []


def apply_filters(spec: Any, f: DashboardFilters | None) -> Applied:
    """The spec with the dashboard filters (and its own calendar ``period``) applied."""
    if isinstance(spec, QuerySpec):
        if not has_filters(f):
            return Applied(spec)
        spec = upcast(spec)
    f = f or DashboardFilters()
    out = Applied(spec)
    if isinstance(spec, NoteSpec):
        return out
    today = now_utc().date()
    period = f.period or spec.period
    days = period_window(period, f.period_from, f.period_to, today)
    bounds = period_bounds(period, today)
    if bounds is not None:
        out.period = period
        out.prev_len = (bounds[0] - bounds[1]).days
    conds = [c.model_dump(mode="json") for c in f.fields]
    if f.period == "custom":
        out.notes.append(f"A custom period counts its {days} days back from today.")
    if isinstance(spec, TasksSpec):
        filters = spec.filters
        upd: dict[str, Any] = {}
        if f.portfolio_id is not None:
            filters = filters.model_copy(update={"portfolio_id": f.portfolio_id})
        if f.assignee:
            filters = filters.model_copy(update={"assignees": list(f.assignee)})
        if days is not None:
            if filters.completed_within_days is not None:
                filters = filters.model_copy(update={"completed_within_days": _clamp(days, 1, 366)})
            if filters.due_within_days is not None and period is not None:
                # "this week": due from today to the period's end, never past it
                left = _period_left(period, today)
                if left is not None:
                    filters = filters.model_copy(update={"due_within_days": left})
            if spec.time_bucket is not None:
                upd["window_days"] = _clamp(days, 7, 366)
        out.spec = spec.model_copy(update={**upd, "filters": filters})
        out.owner = list(f.owner)
        out.fields = conds
    elif isinstance(spec, ProjectsSpec):
        pf = spec.filters
        upd = {}
        if f.portfolio_id is not None:
            pf = pf.model_copy(update={"portfolio_id": f.portfolio_id})
        if f.owner:
            pf = pf.model_copy(update={"owner": list(f.owner)})
        if f.assignee:
            pf = pf.model_copy(update={"assignee": list(f.assignee)})
        if f.fields:
            pf = pf.model_copy(update={"fields": [*pf.fields, *f.fields]})
        if days is not None and spec.time_bucket is not None:
            upd["window_days"] = _clamp(days, 7, 730)
        out.spec = spec.model_copy(update={**upd, "filters": pf})
    elif isinstance(spec, StageSpec | SnapshotSpec):
        upd = {}
        if f.portfolio_id is not None:
            upd["portfolio_id"] = f.portfolio_id
        if f.owner:
            upd["owner"] = list(f.owner)
        if f.fields:
            upd["fields"] = [*spec.fields, *f.fields]
        if days is not None:
            out.window = _clamp(days, 7, 730)
        if f.assignee:
            out.notes.append("The assignee filter doesn't apply to stage or trend widgets.")
        out.spec = spec.model_copy(update=upd)
    return out


def _period_left(period: str, today: date) -> int | None:
    """Days from today to the end of a calendar period (0: today is its last day)."""
    if period == "this_week":
        return 6 - today.weekday()
    if period == "this_month":
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return (nxt - today).days - 1
    if period == "this_quarter":
        q_end_month = 3 * ((today.month - 1) // 3) + 3
        nxt = (today.replace(day=1, month=q_end_month) + timedelta(days=32)).replace(day=1)
        return (nxt - today).days - 1
    return None


async def run_any(
    session: AsyncSession,
    ctx: Ctx,
    kind: str,
    spec: Any,
    *,
    project_id: uuid.UUID | None = None,
    filters: DashboardFilters | None = None,
) -> QueryResultOut:
    """One widget's numbers for this viewer."""
    if isinstance(spec, QuerySpec) and not has_filters(filters):
        return await query.run(session, ctx, kind, spec, project_id=project_id)  # type: ignore[arg-type]
    a = apply_filters(spec, filters)
    s = a.spec
    if isinstance(s, TasksSpec):
        out = await run_tasks(
            session,
            ctx,
            kind,
            s,
            project_id=project_id,
            owner=a.owner,
            fields=a.fields,
            prev_len=a.prev_len,
        )
    elif isinstance(s, ProjectsSpec):
        out = await run_projects(session, ctx, kind, s)
    elif isinstance(s, StageSpec):
        out = await run_stages(session, ctx, kind, s, window_days=a.window, period=a.period)
    elif isinstance(s, SnapshotSpec):
        out = await run_snapshots(session, ctx, kind, s, window_days=a.window, period=a.period)
    elif isinstance(s, NoteSpec):
        out = QueryResultOut(
            kind="note",
            measure="none",
            entity="note",
            description="Note",
            total=0,
            tasks_total=0,
            text=s.text,
            computed_at=now_utc(),
        )
    else:  # pragma: no cover - the models allow nothing else
        raise ValidationFailed("Unknown spec")
    out.notes = [*out.notes, *a.notes]
    return out


async def _project_out(
    session: AsyncSession, ids: list[uuid.UUID], limit: int
) -> list[DrillProjectOut]:
    if not ids:
        return []
    rows = (
        await session.execute(
            select(Project, User.name)
            .outerjoin(User, User.id == Project.owner_id)
            .where(Project.id.in_(ids))
            .order_by(Project.name, Project.id)
            .limit(limit)
        )
    ).all()
    return [
        DrillProjectOut(id=p.id, name=p.name, color=p.color, status=p.status, owner_name=owner)
        for p, owner in rows
    ]


async def drill_any(
    session: AsyncSession, ctx: Ctx, body: DrillAnyIn, split_key: str | None = None
) -> DrillOut:
    spec: Any = body.query_spec
    if isinstance(spec, QuerySpec) and not has_filters(body.filters) and split_key is None:
        return await query.drill(
            session,
            ctx,
            DrillIn(
                query_spec=spec,
                project_id=body.project_id,
                key=body.key,
                bucket_start=body.bucket_start,
                limit=body.limit,
            ),
        )
    a = apply_filters(spec, body.filters)
    s = a.spec
    if isinstance(s, QuerySpec):
        s = upcast(s)
    if isinstance(s, TasksSpec):
        return await drill_tasks(
            session,
            ctx,
            s,
            project_id=body.project_id,
            key=body.key,
            bucket_start=body.bucket_start,
            limit=body.limit,
            split_key=split_key,
            owner=a.owner,
            fields=a.fields,
        )
    if isinstance(s, ProjectsSpec):
        rows = await drill_projects(session, ctx, s, body.key, body.bucket_start)
        projects = [
            DrillProjectOut(
                id=r["id"],
                name=r["name"],
                color=r["color"],
                status=r["status"],
                owner_name=r["owner_name"],
                stage=(r["stage"] or {}).get("label"),
            )
            for r in rows[: body.limit]
        ]
        return DrillOut(
            label="Projects", tasks=[], total=len(rows), entity="projects", projects=projects
        )
    if isinstance(s, StageSpec):
        # a KPI tile drills with no key: a one-stage KPI ("went live this quarter") means its stage
        key = body.key if body.key is not None else (s.stages[0] if len(s.stages) == 1 else None)
        if key is None:
            raise ValidationFailed("Pick a stage to drill into")
        if a.window is not None:
            s = s.model_copy(update={"window_days": a.window})
        ids = await drill_stage(session, ctx, s, key, period=a.period)
        label = next(
            (
                str(o.get("label"))
                for o in (await _stage_options(session, ctx, s))
                if str(o.get("id")) == key
            ),
            "Stage",
        )
        return DrillOut(
            label=label,
            tasks=[],
            total=len(ids),
            entity="projects",
            projects=await _project_out(session, ids, body.limit),
        )
    if isinstance(s, SnapshotSpec):
        ids = await drill_snapshots(session, ctx, s)
        return DrillOut(
            label="Projects",
            tasks=[],
            total=len(ids),
            entity="projects",
            projects=await _project_out(session, ids, body.limit),
        )
    raise ValidationFailed("A note has nothing to drill into")


async def _stage_options(session: AsyncSession, ctx: Ctx, s: StageSpec) -> list[dict[str, Any]]:
    scope = await scope_projects(session, ctx, portfolio_id=s.portfolio_id)
    return [
        o
        for o in (scope.stage_field.options if scope.stage_field else None) or []
        if isinstance(o, dict)
    ]


# ---------- checks (what the models can't see) ----------


async def _field(
    session: AsyncSession,
    ctx: Ctx,
    field_id: uuid.UUID,
    applies_to: str,
    allowed: tuple[str, ...] | None,
    use: str = "",
) -> FieldDef:
    f = await session.get(FieldDef, field_id)
    if (
        f is None
        or f.workspace_id != ctx.workspace_id
        or f.deleted_at is not None
        or f.applies_to != applies_to
    ):
        raise ValidationFailed(
            "That project field doesn't exist"
            if applies_to == "project"
            else "That custom field doesn't exist"
        )
    if allowed is not None and f.type not in allowed:
        raise ValidationFailed(use)
    return f


async def check_any(session: AsyncSession, ctx: Ctx, spec: Any) -> None:
    if isinstance(spec, QuerySpec):
        await query.check_spec(session, ctx, spec)
        return
    if isinstance(spec, TasksSpec):
        await query.check_spec(session, ctx, spec.to_v1())
        if spec.filters.portfolio_id is not None:
            await get_portfolio(session, ctx, spec.filters.portfolio_id)
        if spec.split_field_id is not None:
            await _field(
                session,
                ctx,
                spec.split_field_id,
                "task",
                ("single_select",),
                "A stacked bar splits by priority or a single-select field",
            )
        return
    if isinstance(spec, ProjectsSpec):
        if spec.filters.portfolio_id is not None:
            p = await get_portfolio(session, ctx, spec.filters.portfolio_id)
            if spec.group_by == "stage" and p.stage_field_id is None:
                raise ValidationFailed("This portfolio has no stage field yet", code="no_stage")
        if spec.field_id is not None:
            await _field(
                session,
                ctx,
                spec.field_id,
                "project",
                PROJECT_GROUPABLE,
                "Charts can split by single-select, people or checkbox project fields",
            )
        if spec.measure_field_id is not None:
            await _field(
                session,
                ctx,
                spec.measure_field_id,
                "project",
                NUMERIC,
                "Only number, currency or percent fields add up",
            )
        if spec.time_field_id is not None:
            await _field(
                session, ctx, spec.time_field_id, "project", ("date",), "A time series needs a date"
            )
        for c in spec.filters.fields:
            await _field(session, ctx, c.field_id, "project", None)
        for col in spec.columns:
            if col.startswith("field:"):
                try:
                    fid = uuid.UUID(col.removeprefix("field:"))
                except ValueError:
                    raise ValidationFailed(f"Unknown column {col}") from None
                await _field(session, ctx, fid, "project", None)
        return
    if isinstance(spec, StageSpec):
        p = await get_portfolio(session, ctx, spec.portfolio_id)
        if p.stage_field_id is None:
            raise ValidationFailed("This portfolio has no stage field yet", code="no_stage")
        return
    if isinstance(spec, SnapshotSpec):
        await get_portfolio(session, ctx, spec.portfolio_id)
        if spec.field_id is not None:
            await _field(
                session,
                ctx,
                spec.field_id,
                "project",
                NUMERIC,
                "Only number, currency or percent fields add up",
            )


__all__ = ["apply_filters", "check_any", "drill_any", "project_rows", "run_any", "upcast"]
