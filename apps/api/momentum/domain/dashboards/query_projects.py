"""Phase 7.5 (spec §7.1): the ``projects`` entity, one row per visible project.

Rows reuse the portfolio table's columns (``portfolios.rows.compute_rows``: progress, overdue,
blocked, waiting on customer, stage, target, forecast, slip…), so a dashboard and a portfolio
always agree. A few hundred projects at most, so filters on computed columns, grouping and the
measures run in Python over those rows.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.domain.dashboards.query_scope import Scope, scope_projects
from momentum.domain.dashboards.query_stages import _floor, _next, stays
from momentum.domain.dashboards.schemas import (
    GroupOut,
    PointOut,
    QueryResultOut,
    TimelineItemOut,
)
from momentum.domain.dashboards.schemas_v2 import ProjectsSpec
from momentum.domain.fields.models import FieldDef
from momentum.domain.portfolios.rows import (
    SEVERITY,
    _label,
    _option_order,
    compute_rows,
    sort_value,
)
from momentum.domain.teams.models import Team
from momentum.domain.users.models import User

DEFAULT_COLUMNS = ["name", "owner", "status", "stage", "progress", "target_date", "next_milestone"]
NONE = "none"
STATUS_WORDS = {s: s.replace("_", " ").capitalize() for s in SEVERITY}


async def project_rows(
    session: AsyncSession, ctx: Ctx, spec: ProjectsSpec
) -> tuple[Scope, list[dict[str, Any]], dict[uuid.UUID, FieldDef]]:
    f = spec.filters
    scope = await scope_projects(
        session,
        ctx,
        portfolio_id=f.portfolio_id,
        owner=f.owner,
        assignee=f.assignee,
        fields=[c.model_dump(mode="json") for c in f.fields],
        template_ids=f.template_ids,
        team_ids=f.team_ids,
        status=list(f.status),
        include_completed=f.include_completed,
    )
    defs = {
        d.id: d
        for d in (
            await session.execute(
                select(FieldDef).where(
                    FieldDef.workspace_id == ctx.workspace_id,
                    FieldDef.applies_to == "project",
                    FieldDef.deleted_at.is_(None),
                )
            )
        ).scalars()
    }
    rows = await compute_rows(
        session,
        ctx,
        scope.projects,
        stage_field=scope.stage_field,
        stage_targets=(scope.portfolio.stage_targets if scope.portfolio else None) or {},
        columns=(scope.portfolio.columns if scope.portfolio else None) or [],
        today=datetime.now(UTC).date(),
        live_fields=set(defs),
    )
    team_of = {p.id: p.team_id for p in scope.projects}
    created = {p.id: p.created_at for p in scope.projects}
    for r in rows:
        r["team_id"] = team_of.get(r["id"])
        r["created_at"] = created.get(r["id"])
    if f.slipping:
        rows = [r for r in rows if (r["slip_days"] or 0) > 0]
    if f.has_blocked:
        rows = [r for r in rows if r["blocked"]]
    if f.has_waiting_on_customer:
        rows = [r for r in rows if r["waiting_on_customer"]]
    if f.at_risk:
        rows = [
            r for r in rows if r["status"] in ("at_risk", "off_track") or (r["slip_days"] or 0) > 0
        ]
    return scope, rows, defs


def measure(rows: list[dict[str, Any]], spec: ProjectsSpec) -> float:
    if spec.measure == "count":
        return float(len(rows))
    if spec.measure == "avg_progress":
        vals = [r["progress"] for r in rows if r["progress"] is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0
    if spec.measure == "sum_open_tasks":
        return float(sum(r["open"] for r in rows))
    if spec.measure == "sum_overdue_tasks":
        return float(sum(r["overdue"] for r in rows))
    fid = str(spec.measure_field_id)
    nums = [
        r["fields"][fid]
        for r in rows
        if isinstance(r["fields"].get(fid), int | float) and not isinstance(r["fields"][fid], bool)
    ]
    if spec.measure == "sum_project_field":
        return float(sum(nums))
    return round(sum(nums) / len(nums), 2) if nums else 0.0


async def run_projects(
    session: AsyncSession, ctx: Ctx, kind: str, spec: ProjectsSpec
) -> QueryResultOut:
    scope, rows, defs = await project_rows(session, ctx, spec)
    now = datetime.now(UTC)
    out = QueryResultOut(
        kind=kind,
        measure=spec.measure,
        entity="projects",
        description=describe(spec, scope, defs),
        total=measure(rows, spec),
        tasks_total=len(rows),
        measure_field_name=defs[spec.measure_field_id].name
        if spec.measure_field_id in defs
        else None,
        field_name=defs[spec.field_id].name if spec.field_id in defs else None,
        target=spec.target,
        computed_at=now,
    )
    if kind in ("kpi", "count"):
        out.value = out.total
    elif kind in ("bar", "donut"):
        out.groups = await _groups(session, rows, spec, scope, defs)
    elif kind == "line":
        out.series = await _series(session, rows, spec, scope)
    elif kind == "table":
        out.columns = list(spec.columns or DEFAULT_COLUMNS)
        ordered = _sort(rows, spec.sort, scope)
        out.rows = [_table_row(r, out.columns, defs) for r in ordered[: spec.limit]]
        out.more = max(0, len(rows) - spec.limit)
    elif kind == "timeline":
        out.timeline = _timeline(rows, spec, defs, now.date())
    return out


def _sort(rows: list[dict[str, Any]], key: str | None, scope: Scope) -> list[dict[str, Any]]:
    if not key:
        return rows
    name, _, direction = key.partition(":")
    present = [r for r in rows if sort_value(r, name, scope.stage_field) is not None]
    missing = [r for r in rows if sort_value(r, name, scope.stage_field) is None]
    present.sort(key=lambda r: sort_value(r, name, scope.stage_field), reverse=direction == "desc")
    return present + missing


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


def _table_row(
    r: dict[str, Any], columns: list[str], defs: dict[uuid.UUID, FieldDef]
) -> dict[str, Any]:
    out: dict[str, Any] = {"id": str(r["id"]), "name": r["name"], "color": r["color"]}
    for c in columns:
        if c.startswith("field:"):
            fid = c.removeprefix("field:")
            f = defs.get(uuid.UUID(fid)) if _is_uuid(fid) else None
            v = r["fields"].get(fid)
            out[c] = _label(f, v) if f is not None and f.type == "single_select" else v
        elif c == "owner":
            out[c] = r["owner_name"]
        elif c == "stage":
            out[c] = (r["stage"] or {}).get("label")
        elif c == "next_milestone":
            m = r["next_milestone"]
            out[c] = {"title": m["title"], "due_on": _jsonable(m["due_on"])} if m else None
        elif c == "latest_update":
            u = r["latest_update"]
            out[c] = {"title": u["title"], "status": u["status"]} if u else None
        else:
            out[c] = _jsonable(r.get(c))
    return out


def _is_uuid(v: str) -> bool:
    try:
        uuid.UUID(v)
    except ValueError:
        return False
    return True


async def _groups(
    session: AsyncSession,
    rows: list[dict[str, Any]],
    spec: ProjectsSpec,
    scope: Scope,
    defs: dict[uuid.UUID, FieldDef],
) -> list[GroupOut]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, str] = {NONE: "None"}
    order: list[str] = []
    if spec.group_by == "status":
        for r in rows:
            buckets[r["status"] or NONE].append(r)
        order = [*SEVERITY, NONE]
        labels.update(STATUS_WORDS)
        labels[NONE] = "No status"
    elif spec.group_by == "owner":
        for r in rows:
            buckets[str(r["owner_id"]) if r["owner_id"] else NONE].append(r)
            if r["owner_id"]:
                labels[str(r["owner_id"])] = r["owner_name"] or "Unknown"
        order = [*sorted((k for k in buckets if k != NONE), key=lambda k: labels[k].lower()), NONE]
        labels[NONE] = "No owner"
    elif spec.group_by == "team":
        for r in rows:
            buckets[str(r["team_id"])].append(r)
        teams = {
            str(t.id): t.name
            for t in (
                await session.execute(
                    select(Team).where(Team.id.in_([uuid.UUID(k) for k in buckets]))
                )
            ).scalars()
        }
        labels.update(teams)
        order = sorted(buckets, key=lambda k: labels.get(k, "").lower())
    else:  # stage, project_field
        f = scope.stage_field if spec.group_by == "stage" else defs.get(spec.field_id)  # type: ignore[arg-type]
        if f is None:
            return []
        fid = str(f.id)
        if f.type == "people":
            people: set[str] = set()
            for r in rows:
                vals = r["fields"].get(fid) or []
                for v in vals:
                    buckets[str(v)].append(r)
                    people.add(str(v))
                if not vals:
                    buckets[NONE].append(r)
            names = {
                str(u.id): u.name
                for u in (
                    await session.execute(
                        select(User).where(User.id.in_([uuid.UUID(p) for p in people]))
                    )
                ).scalars()
            }
            labels.update(names)
            order = [*sorted(people, key=lambda k: labels.get(k, "").lower()), NONE]
        else:
            for r in rows:
                v = r["fields"].get(fid)
                buckets[
                    str(v).lower() if isinstance(v, bool) else str(v) if v is not None else NONE
                ].append(r)
            if f.type == "single_select":
                order = [*_option_order(f), NONE]
                labels.update({k: _label(f, k) or k for k in order if k != NONE})
            else:
                order = [*sorted(k for k in buckets if k != NONE), NONE]
                labels.update({"true": "Checked", "false": "Not checked"})
            labels[NONE] = f"No {f.name}"
    out = []
    for k in order:
        members = buckets.get(k, [])
        if not members and (k == NONE or spec.group_by not in ("stage", "project_field")):
            continue
        out.append(
            GroupOut(
                key=k, label=labels.get(k, k), value=measure(members, spec), tasks=len(members)
            )
        )
    return out


async def _series(
    session: AsyncSession, rows: list[dict[str, Any]], spec: ProjectsSpec, scope: Scope
) -> list[PointOut]:
    today = datetime.now(UTC).date()
    start = _floor(today - timedelta(days=spec.window_days), spec.time_bucket or "week")
    bucket = spec.time_bucket or "week"
    dated: list[tuple[date, dict[str, Any]]] = []
    if spec.time_field == "created":
        dated = [(r["created_at"].date(), r) for r in rows if r.get("created_at")]
    elif spec.time_field == "project_field":
        fid = str(spec.time_field_id)
        dated = [
            (date.fromisoformat(r["fields"][fid]), r)
            for r in rows
            if isinstance(r["fields"].get(fid), str)
        ]
    else:  # stage_entered
        by_id = {r["id"]: r for r in rows}
        for s in await stays(session, scope):
            if s.option == spec.stage_option_id and s.project_id in by_id:
                dated.append((s.start.date(), by_id[s.project_id]))
    out = []
    b = start
    while b <= today:
        nxt = _next(b, bucket)
        members = [r for d, r in dated if b <= d < nxt]
        out.append(
            PointOut(
                start=b,
                end=nxt - timedelta(days=1),
                value=measure(members, spec),
                tasks=len(members),
            )
        )
        b = nxt
    return out


def _timeline(
    rows: list[dict[str, Any]], spec: ProjectsSpec, defs: dict[uuid.UUID, FieldDef], today: date
) -> list[TimelineItemOut]:
    until = today + timedelta(days=spec.ahead_days or 90)
    date_fields = [
        defs[uuid.UUID(c.removeprefix("field:"))]
        for c in spec.columns
        if c.startswith("field:")
        and _is_uuid(c.removeprefix("field:"))
        and uuid.UUID(c.removeprefix("field:")) in defs
        and defs[uuid.UUID(c.removeprefix("field:"))].type == "date"
    ]
    items: list[TimelineItemOut] = []
    for r in rows:
        m = r["next_milestone"]
        if m and m["due_on"] and today <= m["due_on"] <= until:
            items.append(
                TimelineItemOut(
                    date=m["due_on"],
                    kind="milestone",
                    title=m["title"],
                    project_id=r["id"],
                    project_name=r["name"],
                )
            )
        for f in date_fields:
            v = r["fields"].get(str(f.id))
            if isinstance(v, str) and today <= date.fromisoformat(v) <= until:
                items.append(
                    TimelineItemOut(
                        date=date.fromisoformat(v),
                        kind="go_live",
                        title=f.name,
                        project_id=r["id"],
                        project_name=r["name"],
                    )
                )
        if not date_fields and r["target_date"] and today <= r["target_date"] <= until:
            items.append(
                TimelineItemOut(
                    date=r["target_date"],
                    kind="target",
                    title="Target date",
                    project_id=r["id"],
                    project_name=r["name"],
                )
            )
    items.sort(key=lambda i: (i.date, i.project_name))
    return items[: max(spec.limit, 50)]


def describe(spec: ProjectsSpec, scope: Scope, defs: dict[uuid.UUID, FieldDef]) -> str:
    what = {
        "count": "Projects",
        "avg_progress": "Average progress",
        "sum_open_tasks": "Open tasks",
        "sum_overdue_tasks": "Overdue tasks",
        "sum_project_field": f"Total {defs[spec.measure_field_id].name}"
        if spec.measure_field_id in defs
        else "Total",
        "avg_project_field": f"Average {defs[spec.measure_field_id].name}"
        if spec.measure_field_id in defs
        else "Average",
    }[spec.measure]
    parts = [what]
    if scope.portfolio is not None:
        parts.append(scope.portfolio.name)
    f = spec.filters
    if f.owner:
        parts.append("owned by " + ("you" if f.owner == ["me"] else "the chosen people"))
    if f.slipping:
        parts.append("slipping")
    if f.at_risk:
        parts.append("at risk")
    if f.fields:
        parts.append(f"{len(f.fields)} field condition{'s' if len(f.fields) > 1 else ''}")
    return " · ".join(parts)


async def drill_projects(
    session: AsyncSession, ctx: Ctx, spec: ProjectsSpec, key: str | None, bucket_start: date | None
) -> list[dict[str, Any]]:
    """The projects behind one bar, slice, point or the whole KPI."""
    scope, rows, defs = await project_rows(session, ctx, spec)
    if key is not None and spec.group_by is not None:
        wanted = {g.key: g for g in await _groups(session, rows, spec, scope, defs)}
        if key not in wanted:
            return []
        rows = [
            r
            for r in rows
            if _key_of(r, spec, scope, defs) == key or key in _keys_of(r, spec, defs)
        ]
    if bucket_start is not None and spec.time_bucket is not None:
        end = _next(_floor(bucket_start, spec.time_bucket), spec.time_bucket)
        series_rows = []
        for r in rows:
            d = r.get("created_at")
            if spec.time_field == "created" and d and bucket_start <= d.date() < end:
                series_rows.append(r)
        rows = series_rows if spec.time_field == "created" else rows
    return rows


def _key_of(
    r: dict[str, Any], spec: ProjectsSpec, scope: Scope, defs: dict[uuid.UUID, FieldDef]
) -> str:
    if spec.group_by == "status":
        return r["status"] or NONE
    if spec.group_by == "owner":
        return str(r["owner_id"]) if r["owner_id"] else NONE
    if spec.group_by == "team":
        return str(r["team_id"])
    f = scope.stage_field if spec.group_by == "stage" else defs.get(spec.field_id)  # type: ignore[arg-type]
    if f is None:
        return NONE
    v = r["fields"].get(str(f.id))
    if isinstance(v, bool):
        return str(v).lower()
    return str(v) if v is not None and not isinstance(v, list) else NONE


def _keys_of(r: dict[str, Any], spec: ProjectsSpec, defs: dict[uuid.UUID, FieldDef]) -> list[str]:
    if spec.group_by == "project_field" and spec.field_id in defs:
        v = r["fields"].get(str(spec.field_id))
        if isinstance(v, list):
            return [str(x) for x in v]
    return []
