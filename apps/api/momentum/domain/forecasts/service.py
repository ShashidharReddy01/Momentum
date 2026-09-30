"""S6.5.3: project forecasts and risk scores. The one write path for ``forecasts`` rows.

``compute()`` forecasts a project **as of any date** from what was known then (tasks that
existed, work finished by that day), so the nightly job and the backtest (``backtest.py``) run the
same code. The Monte Carlo (``montecarlo.py``) bootstraps the project's own weekly throughput
over the last 12 weeks: tasks per week, or estimated hours per week when most work (remaining and
recently finished) is estimated, each week paired with the work added to the project that week
(scope growth). The critical chain of open dependent work sets a floor.

``risk()`` scores 0-100 from Radar's signals (``signals.py``, one definition) plus the forecast
against the project's due date, and keeps the strongest drivers in words. Radar reads the stored
score instead of recomputing when a forecast is fresh.

Visibility: a forecast is about the project's own tasks, so whoever can see the project sees it.
"""

from __future__ import annotations

import random
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Actor, Ctx
from momentum.core.events import emit
from momentum.core.settings import Settings
from momentum.domain.access import get_visible_project
from momentum.domain.forecasts.models import Forecast
from momentum.domain.forecasts.montecarlo import (
    longest_chain,
    percentiles,
    simulate,
    weekly_throughput,
)
from momentum.domain.forecasts.signals import signals
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject

HISTORY_WEEKS = 12
MIN_WEEKS = 2  # of history before a forecast means anything
ESTIMATED_SHARE = 0.7  # of open and of recently finished work, to forecast in hours
SIGNAL_POINTS = 12  # risk points per Radar signal weight
FRESH = timedelta(hours=36)  # Radar trusts a stored forecast this old


@dataclass
class Result:
    as_of: date
    status: str  # ok | done | no_history
    p50: date | None = None
    p80: date | None = None
    p95: date | None = None
    inputs: dict[str, Any] = field(default_factory=dict)


def _day(ts: datetime) -> date:
    return ts.astimezone(UTC).date()


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"  # no %-d: it fails on Windows


async def compute(session: AsyncSession, project: Project, as_of: date, *, runs: int) -> Result:
    """The forecast for ``project`` as it would have been made on ``as_of``."""
    rows = (
        await session.execute(
            select(
                Task.id,
                Task.created_at,
                Task.completed_at,
                Task.estimate_minutes,
                Task.start_on,
                Task.due_on,
            )
            .join(TaskProject, TaskProject.task_id == Task.id)
            .where(
                TaskProject.project_id == project.id,
                Task.parent_id.is_(None),
                Task.deleted_at.is_(None),
            )
        )
    ).all()
    existed = [r for r in rows if _day(r.created_at) <= as_of]
    done = [r for r in existed if r.completed_at is not None and _day(r.completed_at) <= as_of]
    done_ids = {r.id for r in done}
    open_ = [r for r in existed if r.id not in done_ids]
    if not open_:
        return Result(as_of, "done", inputs={"remaining": 0, "mode": "tasks"})
    start = min(_day(r.created_at) for r in existed)
    weeks = min(HISTORY_WEEKS, (as_of - start).days // 7)
    window = [r for r in done if (as_of - _day(r.completed_at)).days < weeks * 7]
    if weeks < MIN_WEEKS or not window:
        return Result(
            as_of,
            "no_history",
            inputs={"remaining": len(open_), "mode": "tasks", "weeks": max(0, weeks)},
        )

    estimated_open = [r for r in open_ if r.estimate_minutes]
    estimated_done = [r for r in window if r.estimate_minutes]
    hours = len(estimated_open) >= ESTIMATED_SHARE * len(open_) and len(
        estimated_done
    ) >= ESTIMATED_SHARE * len(window)
    if hours:
        typical = statistics.median(r.estimate_minutes for r in [*estimated_open, *estimated_done])

        def amount(r: Any) -> float:
            return float(r.estimate_minutes or typical)

        remaining = sum(amount(r) for r in open_)
    else:

        def amount(r: Any) -> float:
            return 1.0

        remaining = float(len(open_))
    samples = weekly_throughput(
        [((as_of - _day(r.completed_at)).days, amount(r)) for r in window], weeks
    )
    # scope growth: work added after the project's first day, in the same weeks
    added = weekly_throughput(
        [
            ((as_of - _day(r.created_at)).days, amount(r))
            for r in existed
            if _day(r.created_at) > start and (as_of - _day(r.created_at)).days < weeks * 7
        ],
        weeks,
    )

    open_ids = {r.id for r in open_}
    edges = (
        await session.execute(
            select(TaskDependency.task_id, TaskDependency.depends_on_id).where(
                TaskDependency.task_id.in_(open_ids), TaskDependency.depends_on_id.in_(open_ids)
            )
        )
    ).all()
    durations = {
        str(r.id): (r.due_on - r.start_on).days + 1
        if r.start_on and r.due_on and r.due_on >= r.start_on
        else 1
        for r in open_
    }
    chain = longest_chain(durations, [(str(a), str(b)) for a, b in edges])
    # stable for a given day; a simulation, not security
    rng = random.Random(f"{project.id}:{as_of.isoformat()}")  # noqa: S311
    days = simulate(remaining, samples, runs=runs, rng=rng, floor_days=chain, added=added)
    inputs: dict[str, Any] = {
        "mode": "hours" if hours else "tasks",
        "remaining": round(remaining / 60, 1) if hours else int(remaining),
        "remaining_tasks": len(open_),
        "weeks": weeks,
        "throughput": [round(s / 60, 1) if hours else s for s in samples],
        "added": [round(a / 60, 1) if hours else a for a in added],
        "chain_days": chain,
        "runs": runs,
    }
    if days is None:
        return Result(as_of, "no_history", inputs=inputs)
    p = percentiles(days)
    return Result(
        as_of,
        "ok",
        p50=as_of + timedelta(days=p.p50),
        p80=as_of + timedelta(days=p.p80),
        p95=as_of + timedelta(days=p.p95),
        inputs=inputs,
    )


def _level(score: float) -> str:
    return "high" if score >= 60 else "medium" if score >= 30 else "low" if score > 0 else "none"


async def risk(
    session: AsyncSession, project: Project, result: Result, now: datetime
) -> tuple[float, str, list[dict[str, Any]]]:
    """(score 0-100, level, drivers strongest first): Radar's signals, plus the forecast
    against the due date when there is one."""
    found = await signals(session, project.id, result.as_of, now)
    drivers = [
        {
            "kind": s["kind"],
            "text": s["text"],
            "tasks": s["tasks"],
            "points": SIGNAL_POINTS * int(s["weight"]),
        }
        for s in found
    ]
    due = project.due_on
    if due is not None and result.status == "ok":
        assert result.p50 and result.p80 and result.p95
        if result.p50 > due:
            late = (result.p50 - due).days
            drivers.append(
                {
                    "kind": "forecast",
                    "text": f"Likely to finish {_fmt(result.p50)}, {late} "
                    f"{'day' if late == 1 else 'days'} after the {_fmt(due)} due date",
                    "tasks": [],
                    "points": 40,
                }
            )
        elif result.p80 > due:
            drivers.append(
                {
                    "kind": "forecast",
                    "text": f"A real chance of missing the {_fmt(due)} due date: "
                    f"80% likely by {_fmt(result.p80)}",
                    "tasks": [],
                    "points": 25,
                }
            )
        elif result.p95 > due:
            drivers.append(
                {
                    "kind": "forecast",
                    "text": f"A small chance of missing the {_fmt(due)} due date: "
                    f"95% likely by {_fmt(result.p95)}",
                    "tasks": [],
                    "points": 10,
                }
            )
    drivers.sort(key=lambda d: -int(d["points"]))
    score = float(min(100, sum(int(d["points"]) for d in drivers)))
    return score, _level(score), drivers


def _system(settings: Settings, workspace_id: uuid.UUID) -> Ctx:
    return Ctx(actor=Actor(id=None, workspace_id=workspace_id), settings=settings, via="system")


async def store(
    session: AsyncSession,
    ctx: Ctx,
    project: Project,
    *,
    as_of: date | None = None,
    now: datetime | None = None,
) -> Forecast:
    """Compute and save a project's forecast (the one write path for ``forecasts``)."""
    now = now or datetime.now(UTC)
    as_of = as_of or now.date()
    result = await compute(session, project, as_of, runs=ctx.settings.forecast_runs)
    score, lvl, drivers = await risk(session, project, result, now)
    row = Forecast(
        workspace_id=project.workspace_id,
        project_id=project.id,
        computed_at=now,
        as_of=as_of,
        status=result.status,
        p50=result.p50,
        p80=result.p80,
        p95=result.p95,
        risk_score=score,
        risk_level=lvl,
        drivers=drivers,
        inputs=result.inputs,
    )
    session.add(row)
    await session.flush()
    await emit(
        session,
        ctx,
        type="project.forecast_updated",
        entity_type="project",
        entity_id=project.id,
        data={"status": result.status, "risk_level": lvl},
        channels=[f"project:{project.id}"],
    )
    return row


async def latest(session: AsyncSession, project_id: uuid.UUID) -> Forecast | None:
    return (
        await session.execute(
            select(Forecast)
            .where(Forecast.project_id == project_id)
            .order_by(Forecast.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def fresh(session: AsyncSession, project_id: uuid.UUID, now: datetime) -> Forecast | None:
    """The latest forecast if it was computed recently enough to rely on (Radar)."""
    f = await latest(session, project_id)
    return f if f is not None and now - f.computed_at <= FRESH else None


async def get_forecast(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID
) -> tuple[Project, Forecast | None]:
    project, _ = await get_visible_project(session, ctx, project_id)
    return project, await latest(session, project.id)


async def refresh(session: AsyncSession, ctx: Ctx, project_id: uuid.UUID) -> Forecast:
    """Recompute now (anyone who can see the project: it changes no one's work)."""
    project, _ = await get_visible_project(session, ctx, project_id)
    return await store(session, ctx, project)


async def run_all(session: AsyncSession, settings: Settings, now: datetime | None = None) -> int:
    """The nightly job: a fresh forecast for every active project (not archived, deleted or a
    template), each workspace acting as the system."""
    now = now or datetime.now(UTC)
    projects = list(
        (
            await session.execute(
                select(Project).where(
                    Project.deleted_at.is_(None),
                    Project.archived_at.is_(None),
                    Project.is_template.is_(False),
                )
            )
        ).scalars()
    )
    for p in projects:
        await store(session, _system(settings, p.workspace_id), p, now=now)
    return len(projects)
