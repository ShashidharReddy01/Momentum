"""Phase 7.5 (spec §7.1): lifecycle analytics over a portfolio's stage field history
(``project_field_events``), for the projects of the portfolio the viewer can see.

- ``funnel``: projects that reached each stage in the window, with conversion from the stage
  before (in lifecycle order).
- ``time_in_stage``: per stage, the median, 75th and 90th percentile of days spent, over the
  stays that ended in the window, next to the stage's target.
- ``throughput``: how many entered the chosen stages per time bucket (a KPI compares the window
  with the one before it).
- ``aging``: the projects in each stage now, by how long they've been there (0-7, 8-14, 15-30,
  31-60, 60+ days), with how many are past the stage's target.
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.dashboards.query_scope import (
    Scope,
    day_start,
    days_between,
    now_utc,
    period_bounds,
    scope_projects,
)
from momentum.domain.dashboards.schemas import PointOut, QueryResultOut, StageStatOut
from momentum.domain.dashboards.schemas_v2 import AGING_BUCKETS, StageSpec
from momentum.domain.fields.models import ProjectFieldEvent, ProjectFieldValue


@dataclass
class Stay:
    project_id: uuid.UUID
    option: str
    start: datetime
    end: datetime | None  # None: still there


def _floor(d: date, bucket: str) -> date:
    if bucket == "day":
        return d
    if bucket == "week":
        return d - timedelta(days=d.weekday())
    return d.replace(day=1)


def _next(d: date, bucket: str) -> date:
    if bucket == "day":
        return d + timedelta(days=1)
    if bucket == "week":
        return d + timedelta(days=7)
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _pct(values: list[float], q: float) -> float:
    if len(values) == 1:
        return round(values[0], 1)
    cuts = statistics.quantiles(sorted(values), n=100, method="inclusive")
    return round(cuts[int(q * 100) - 1], 1)


async def stays(session: AsyncSession, scope: Scope) -> list[Stay]:
    """Every stay in a stage, from the stage field's history (an undo is a change too)."""
    if scope.stage_field is None:
        return []
    rows = (
        await session.execute(
            select(ProjectFieldEvent.project_id, ProjectFieldEvent.new, ProjectFieldEvent.at)
            .where(
                ProjectFieldEvent.project_id.in_(scope.ids),
                ProjectFieldEvent.field_id == scope.stage_field.id,
            )
            .order_by(ProjectFieldEvent.project_id, ProjectFieldEvent.at, ProjectFieldEvent.id)
        )
    ).all()
    out: list[Stay] = []
    open_: dict[uuid.UUID, Stay] = {}
    for pid, new, at in rows:
        current = open_.pop(pid, None)
        if current is not None:
            current.end = at
        if isinstance(new, str):
            stay = Stay(pid, new, at, None)
            out.append(stay)
            open_[pid] = stay
    return out


def options(scope: Scope, only: list[str]) -> list[tuple[str, str]]:
    opts = [
        (str(o["id"]), str(o.get("label", "")))
        for o in (scope.stage_field.options if scope.stage_field else None) or []
        if isinstance(o, dict)
    ]
    return [o for o in opts if not only or o[0] in only]


async def run_stages(
    session: AsyncSession,
    ctx: Ctx,
    kind: str,
    spec: StageSpec,
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
    if scope.stage_field is None:
        raise ValidationFailed("This portfolio has no stage field yet", code="no_stage")
    assert scope.portfolio is not None
    window = window_days or spec.window_days
    now = now_utc()
    start = now - timedelta(days=window)
    before = start - timedelta(days=window)  # the previous period (a KPI compares)
    bounds = period_bounds(period, now.date())
    if bounds is not None:  # a calendar period: from its first day, against the one before
        start, before = day_start(bounds[0]), day_start(bounds[1])
        window = (now.date() - bounds[0]).days + 1
    opts = options(scope, spec.stages)
    targets: dict[str, Any] = scope.portfolio.stage_targets or {}
    all_stays = await stays(session, scope)
    out = QueryResultOut(
        kind=kind,
        measure=spec.analysis,
        entity="stage_events",
        description=_describe(spec, window, scope, period),
        total=0,
        tasks_total=len(scope.projects),
        computed_at=now,
    )

    if spec.analysis == "funnel":
        reached: dict[str, set[uuid.UUID]] = defaultdict(set)
        for s in all_stays:
            if s.start >= start:
                reached[s.option].add(s.project_id)
        previous: int | None = None
        for oid, label in opts:
            n = len(reached[oid])
            out.stages.append(
                StageStatOut(
                    option_id=oid,
                    label=label,
                    count=n,
                    conversion=round(n / previous, 4) if previous else None,
                )
            )
            previous = n
        out.total = float(sum(st.count for st in out.stages[:1]))
    elif spec.analysis == "time_in_stage":
        by_stage: dict[str, list[float]] = defaultdict(list)
        for s in all_stays:
            if s.end is not None and s.end >= start:
                by_stage[s.option].append(days_between(s.start, s.end))
        for oid, label in opts:
            vals = by_stage[oid]
            target = targets.get(oid)
            out.stages.append(
                StageStatOut(
                    option_id=oid,
                    label=label,
                    count=len(vals),
                    median_days=round(statistics.median(vals), 1) if vals else None,
                    p75_days=_pct(vals, 0.75) if vals else None,
                    p90_days=_pct(vals, 0.90) if vals else None,
                    target_days=int(target) if isinstance(target, int | float) else None,
                )
            )
        medians = [st.median_days for st in out.stages if st.median_days is not None]
        out.value = medians[0] if kind == "kpi" and len(medians) == 1 else None
        out.total = float(sum(st.count for st in out.stages))
    elif spec.analysis == "throughput":
        wanted = {o for o, _l in opts}
        entered = [s for s in all_stays if s.option in wanted]
        current = [s for s in entered if s.start >= start]
        out.value = float(len(current))
        out.total = float(len(current))
        if spec.compare_previous:
            out.previous = float(len([s for s in entered if before <= s.start < start]))
        today = now.date()
        b = _floor(start.date(), spec.time_bucket)
        while b <= today:
            nxt = _next(b, spec.time_bucket)
            n = sum(1 for s in current if b <= s.start.date() < nxt)
            out.series.append(PointOut(start=b, end=nxt - timedelta(days=1), value=n, tasks=n))
            b = nxt
    else:  # aging
        values = {
            pid: v
            for pid, v in (
                await session.execute(
                    select(ProjectFieldValue.project_id, ProjectFieldValue.value).where(
                        ProjectFieldValue.project_id.in_(scope.ids),
                        ProjectFieldValue.field_id == scope.stage_field.id,
                    )
                )
            ).tuples()
        }
        entered_at: dict[uuid.UUID, datetime] = {}
        for s in all_stays:
            if s.end is None:
                entered_at[s.project_id] = s.start
        for oid, label in opts:
            target = targets.get(oid)
            buckets = [0] * len(AGING_BUCKETS)
            breaches = n = 0
            for pid, v in values.items():
                if v != oid or pid not in entered_at:
                    continue
                age = int(days_between(entered_at[pid], now))
                n += 1
                for i, (lo, hi) in enumerate(AGING_BUCKETS):
                    if age >= lo and (hi is None or age <= hi):
                        buckets[i] += 1
                        break
                if isinstance(target, int | float) and age > target:
                    breaches += 1
            out.stages.append(
                StageStatOut(
                    option_id=oid,
                    label=label,
                    count=n,
                    buckets=buckets,
                    breaches=breaches,
                    target_days=int(target) if isinstance(target, int | float) else None,
                )
            )
        out.total = float(sum(st.count for st in out.stages))
    return out


def _describe(spec: StageSpec, window: int, scope: Scope, period: str | None = None) -> str:
    what = {
        "funnel": "Projects reaching each stage",
        "time_in_stage": "Days in each stage",
        "throughput": "Projects entering",
        "aging": "Projects in each stage now, by days there",
    }[spec.analysis]
    where = scope.portfolio.name if scope.portfolio else "the portfolio"
    if spec.analysis == "aging":
        return f"{what} · {where}"
    if period is not None and period != "custom":
        return f"{what} · {where} · {period.replace('_', ' ')}"
    return f"{what} · {where} · last {window} days"


async def drill_stage(
    session: AsyncSession, ctx: Ctx, spec: StageSpec, option_id: str
) -> list[uuid.UUID]:
    """The projects behind one stage of a stage analysis (for the drill)."""
    scope = await scope_projects(
        session,
        ctx,
        portfolio_id=spec.portfolio_id,
        owner=spec.owner,
        fields=[c.model_dump(mode="json") for c in spec.fields],
    )
    if scope.stage_field is None:
        return []
    start = now_utc() - timedelta(days=spec.window_days)
    all_stays = await stays(session, scope)
    if spec.analysis == "aging":
        return sorted({s.project_id for s in all_stays if s.end is None and s.option == option_id})
    if spec.analysis == "time_in_stage":
        return sorted(
            {
                s.project_id
                for s in all_stays
                if s.option == option_id and s.end is not None and s.end >= start
            }
        )
    return sorted({s.project_id for s in all_stays if s.option == option_id and s.start >= start})
