"""S6.5.3 Forecasting and risk score: the Monte Carlo core (pure), a forecast as of any date from
what was known then, statuses when there's nothing to go on, the risk score and its drivers, the
API (visibility, refresh, the realtime event), Radar reading a fresh stored forecast, the
deterministic synthetic history, and the backtest's calibration."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from momentum.agents.radar import note_from_forecast
from momentum.core.db import UnitOfWork
from momentum.core.events import OutboxEvent
from momentum.core.settings import Settings
from momentum.domain.forecasts import service
from momentum.domain.forecasts.backtest import backtest
from momentum.domain.forecasts.models import Forecast
from momentum.domain.forecasts.montecarlo import (
    longest_chain,
    percentiles,
    simulate,
    weekly_throughput,
)
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject
from momentum.seed_history import seed_history
from tests.helpers import Clients

B = "/api/v1"


# ---------- the Monte Carlo core ----------


def test_weekly_throughput_counts_empty_weeks() -> None:
    # (days before the forecast date, amount): today and 3 days ago are this week; 8 days ago is
    # last week; 30 days ago is outside a 3-week window
    assert weekly_throughput([(0, 1), (3, 1), (8, 2), (30, 1)], 3) == [0.0, 2.0, 2.0]


def test_simulate_is_deterministic_and_ordered() -> None:
    a = simulate(20, [3, 5, 0, 4], runs=2000, rng=random.Random(1))
    b = simulate(20, [3, 5, 0, 4], runs=2000, rng=random.Random(1))
    assert a == b and a is not None
    p = percentiles(a)
    assert 0 < p.p50 <= p.p80 <= p.p95
    # 20 tasks at 3-5 a week (with a zero week) take about four to eight weeks
    assert 21 <= p.p50 <= 49


def test_simulate_edges() -> None:
    assert simulate(5, [0, 0, 0], runs=10, rng=random.Random(1)) is None  # never finished anything
    assert simulate(0, [2], runs=3, rng=random.Random(1)) == [0, 0, 0]  # nothing left
    # the critical chain is a floor however fast the team is
    days = simulate(1, [10], runs=5, rng=random.Random(1), floor_days=9)
    assert days == [9] * 5


def test_longest_chain() -> None:
    durations = {"a": 2, "b": 3, "c": 1, "d": 5}
    # a <- b <- c (c waits on b, b on a), d alone
    assert longest_chain(durations, [("b", "a"), ("c", "b")]) == 6
    assert longest_chain(durations, [("b", "a"), ("a", "b")]) >= 5  # a cycle doesn't loop


# ---------- a forecast from real rows ----------


async def _project(uow: UnitOfWork, name: str = "Website Revamp") -> Project:
    async with uow.transaction() as s:
        return (await s.execute(select(Project).where(Project.name == name))).scalar_one()


async def _history(uow: UnitOfWork, project: Project, weeks: int, per_week: int, left: int) -> None:
    """Replace the project's tasks with ones created ``weeks`` ago, ``per_week`` finished every
    week since, and ``left`` still open."""
    now = datetime.now(UTC)
    start = now - timedelta(weeks=weeks)
    async with uow.transaction() as s:
        ids = (
            await s.execute(select(TaskProject.task_id).where(TaskProject.project_id == project.id))
        ).scalars()
        for t in (await s.execute(select(Task).where(Task.id.in_(list(ids))))).scalars():
            t.deleted_at = now
        section_id = (
            await s.execute(
                select(TaskProject.section_id).where(TaskProject.project_id == project.id).limit(1)
            )
        ).scalar_one()
        p = await s.get(Project, project.id)
        assert p is not None
        from momentum.domain.workspace.models import Workspace

        ws = await s.get(Workspace, p.workspace_id)
        assert ws is not None
        n = weeks * per_week + left
        for i in range(n):
            ws.task_seq += 1
            done = None
            if i < weeks * per_week:
                done = start + timedelta(days=7 * (i // per_week) + 3)
            t = Task(
                workspace_id=p.workspace_id,
                number=ws.task_seq,
                title=f"History {i}",
                created_at=start,
                completed_at=done,
            )
            s.add(t)
            await s.flush()
            s.add(
                TaskProject(
                    task_id=t.id, project_id=p.id, section_id=section_id, position=f"a{i:04d}"
                )
            )


async def test_a_steady_pace_forecasts_the_remaining_work(
    uow: UnitOfWork, settings: Settings, seeded: None
) -> None:
    project = await _project(uow)
    await _history(uow, project, weeks=6, per_week=4, left=12)  # 12 left at 4 a week
    async with uow.transaction() as s:
        r = await service.compute(s, project, datetime.now(UTC).date(), runs=2000)
    assert r.status == "ok" and r.inputs["mode"] == "tasks" and r.inputs["remaining"] == 12
    today = datetime.now(UTC).date()
    assert r.p50 and r.p80 and r.p95
    # three weeks at a steady four a week, give or take the current week's partial count
    assert today + timedelta(days=14) <= r.p50 <= r.p80 <= r.p95 <= today + timedelta(days=35)


async def test_a_forecast_as_of_the_past_ignores_what_came_later(
    uow: UnitOfWork, seeded: None
) -> None:
    project = await _project(uow)
    await _history(uow, project, weeks=6, per_week=4, left=0)  # all done by now
    today = datetime.now(UTC).date()
    async with uow.transaction() as s:
        assert (await service.compute(s, project, today, runs=200)).status == "done"
        past = await service.compute(s, project, today - timedelta(days=21), runs=2000)
    assert past.status == "ok" and past.inputs["remaining"] == 12  # the last three weeks' work


async def test_no_history_and_done(uow: UnitOfWork, seeded: None) -> None:
    project = await _project(uow)
    await _history(uow, project, weeks=1, per_week=2, left=5)  # one week: too little to go on
    async with uow.transaction() as s:
        r = await service.compute(s, project, datetime.now(UTC).date(), runs=100)
    assert r.status == "no_history" and r.p50 is None


async def test_risk_counts_the_forecast_against_the_due_date(
    uow: UnitOfWork, settings: Settings, seeded: None
) -> None:
    project = await _project(uow)
    await _history(uow, project, weeks=6, per_week=2, left=20)  # ten weeks of work left
    async with uow.transaction() as s:
        p = await s.get(Project, project.id)
        assert p is not None
        p.due_on = datetime.now(UTC).date() + timedelta(days=14)
        from tests.helpers import ctx_for

    ctx = await ctx_for(uow, settings, "ravi")
    async with uow.transaction() as s:
        p = await s.get(Project, project.id)
        assert p is not None
        f = await service.store(s, ctx, p)
    assert f.status == "ok" and f.risk_level in ("medium", "high")
    top = f.drivers[0]
    assert top["kind"] == "forecast" and top["points"] == 40
    assert top["text"].startswith("Likely to finish") and "after the" in top["text"]


# ---------- the API ----------


async def test_api_visibility_refresh_and_event(as_user: Clients, uow: UnitOfWork) -> None:
    ravi, mei = await as_user("ravi"), await as_user("mei")
    projects = {p["name"]: p["id"] for p in (await ravi.get(f"{B}/projects")).json()["data"]}
    pid = projects["Website Revamp"]
    assert (await ravi.get(f"{B}/projects/{pid}/forecast")).json() == {"forecast": None}
    r = await ravi.post(f"{B}/projects/{pid}/forecast")
    assert r.status_code == 200, r.text
    f = r.json()["forecast"]
    assert f["status"] in ("ok", "no_history", "done") and f["risk_level"] in (
        "none",
        "low",
        "medium",
        "high",
    )
    assert (await mei.get(f"{B}/projects/{pid}/forecast")).json()["forecast"]["id"] == f["id"]
    async with uow.transaction() as s:
        ev = (
            await s.execute(
                select(OutboxEvent).where(OutboxEvent.type == "project.forecast_updated")
            )
        ).scalar_one()
        assert f"project:{pid}" in ev.payload["channels"]
    private = projects["Mobile App v2"]  # mei isn't in it
    assert (await mei.get(f"{B}/projects/{private}/forecast")).status_code == 404
    assert (await mei.post(f"{B}/projects/{private}/forecast")).status_code == 404


async def test_the_nightly_job_skips_archived_projects(
    uow: UnitOfWork, settings: Settings, seeded: None
) -> None:
    async with uow.transaction() as s:
        n = await service.run_all(s, settings)
        rows = (await s.execute(select(Forecast))).scalars().all()
    assert n == len(rows) and n >= 4
    async with uow.transaction() as s:
        archived = (
            (await s.execute(select(Project).where(Project.archived_at.is_not(None))))
            .scalars()
            .all()
        )
        assert not {p.id for p in archived} & {f.project_id for f in rows}


# ---------- Radar reads the stored score ----------


def test_radar_note_from_a_forecast() -> None:
    f = Forecast(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        computed_at=datetime.now(UTC),
        as_of=date.today(),
        status="ok",
        risk_score=52,
        risk_level="medium",
        drivers=[
            {
                "kind": "forecast",
                "text": "Likely to finish Nov 12, 9 days after",
                "tasks": [],
                "points": 40,
            },
            {
                "kind": "unassigned",
                "text": "1 task(s) due within 3 days",
                "tasks": ["T-4 X"],
                "points": 12,
            },
        ],
        inputs={},
    )
    level, found = note_from_forecast(f)
    assert level == "medium"
    assert [s["kind"] for s in found] == ["forecast", "unassigned"]
    assert found[1]["tasks"] == ["T-4 X"]


# ---------- synthetic history and the backtest ----------


async def test_history_is_deterministic_and_the_backtest_is_calibrated(
    uow: UnitOfWork, settings: Settings, seeded: None
) -> None:
    async with uow.transaction() as s:
        made = await seed_history(s, settings)
        again = await seed_history(s, settings)
    assert made["history_projects"] == 20 and made["history_tasks"] > 400
    assert again["history_projects"] == 0  # safe to re-run
    async with uow.transaction() as s:
        report = await backtest(s, runs=settings.forecast_runs)
    assert len(report.scored) == 20
    assert report.passed, "\n".join(report.lines())
