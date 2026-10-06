"""Phase 7.5 (spec §7.1): the ``snapshots`` entity, a time series read from ``project_snapshots``
across a portfolio's projects the viewer can see.

Each bucket shows the metric on the last snapshot day inside it (today's partial bucket: the latest
day there is). ``open`` and ``overdue`` add up across projects, ``progress_avg`` averages the
projects that have a progress, ``sum_project_field`` adds up one number field. A project with no
snapshot that day simply isn't counted that day (nothing is filled in).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.domain.dashboards.query_scope import now_utc, period_bounds, scope_projects
from momentum.domain.dashboards.query_stages import _floor, _next
from momentum.domain.dashboards.schemas import PointOut, QueryResultOut
from momentum.domain.dashboards.schemas_v2 import SnapshotSpec
from momentum.domain.fields.models import FieldDef
from momentum.domain.projects.models import ProjectSnapshot

WORDS = {
    "open": "Open tasks",
    "overdue": "Overdue tasks",
    "progress_avg": "Average progress",
    "sum_project_field": "Total",
}


def _metric(spec: SnapshotSpec, rows: list[dict[str, Any]]) -> tuple[float, int]:
    """The metric over one day's snapshot rows, and how many projects it counted."""
    if spec.metric in ("open", "overdue"):
        vals = [r.get(spec.metric) for r in rows]
        nums = [float(v) for v in vals if isinstance(v, int | float)]
        return float(sum(nums)), len(nums)
    if spec.metric == "progress_avg":
        nums = [float(r["progress"]) for r in rows if isinstance(r.get("progress"), int | float)]
        return (round(sum(nums) / len(nums), 4) if nums else 0.0), len(nums)
    fid = str(spec.field_id)
    nums = [
        float(v)
        for r in rows
        if isinstance(v := (r.get("fields") or {}).get(fid), int | float)
        and not isinstance(v, bool)
    ]
    return float(sum(nums)), len(nums)


async def run_snapshots(
    session: AsyncSession,
    ctx: Ctx,
    kind: str,
    spec: SnapshotSpec,
    window_days: int | None = None,
    period: str | None = None,
) -> QueryResultOut:
    scope = await scope_projects(
        session,
        ctx,
        portfolio_id=spec.portfolio_id,
        owner=spec.owner,
        fields=[c.model_dump(mode="json") for c in spec.fields],
    )
    window = window_days or spec.window_days
    now = now_utc()
    today = now.date()
    start = today - timedelta(days=window)
    prev_start = start - timedelta(days=window)
    bounds = period_bounds(period, today)
    if bounds is not None:
        start, prev_start = bounds
    field_name = None
    if spec.field_id is not None:
        f = await session.get(FieldDef, spec.field_id)
        field_name = f.name if f is not None and f.deleted_at is None else None
    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    lookback = prev_start if spec.compare_previous else start
    for day, data in (
        await session.execute(
            select(ProjectSnapshot.day, ProjectSnapshot.data).where(
                ProjectSnapshot.project_id.in_(scope.ids),
                ProjectSnapshot.day >= lookback,
                ProjectSnapshot.day <= today,
            )
        )
    ).tuples():
        by_day[day].append(data)
    days = sorted(by_day)

    def at(last: date, first: date) -> tuple[float, int] | None:
        inside = [d for d in days if first <= d <= last]
        return _metric(spec, by_day[inside[-1]]) if inside else None

    what = WORDS[spec.metric] + (f" {field_name}" if field_name else "")
    where = scope.portfolio.name if scope.portfolio else "the portfolio"
    out = QueryResultOut(
        kind=kind,
        measure=spec.metric,
        entity="snapshots",
        description=f"{what} · {where} · daily snapshots",
        total=0,
        tasks_total=len(scope.projects),
        measure_field_name=field_name,
        target=spec.target,
        computed_at=now,
    )
    latest = at(today, start)
    out.total = latest[0] if latest else 0
    if kind == "kpi":
        out.value = latest[0] if latest else None
        if spec.compare_previous:
            before = at(start - timedelta(days=1), prev_start)
            out.previous = before[0] if before else None
        if not days:
            out.notes.append("No snapshots yet: they are written nightly.")
        return out
    b = _floor(start, spec.time_bucket)
    while b <= today:
        nxt = _next(b, spec.time_bucket)
        point = at(min(nxt - timedelta(days=1), today), b)
        if point is not None:
            out.series.append(
                PointOut(start=b, end=nxt - timedelta(days=1), value=point[0], tasks=point[1])
            )
        b = nxt
    if not out.series:
        out.notes.append("No snapshots in this window yet: they are written nightly.")
    return out


async def drill_snapshots(session: AsyncSession, ctx: Ctx, spec: SnapshotSpec) -> list[uuid.UUID]:
    """The projects a snapshot series covers (the drill lists them as they are now)."""
    scope = await scope_projects(
        session,
        ctx,
        portfolio_id=spec.portfolio_id,
        owner=spec.owner,
        fields=[c.model_dump(mode="json") for c in spec.fields],
    )
    return [p.id for p in scope.projects]
