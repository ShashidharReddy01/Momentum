"""S6.5.3: forecast backtest (the phase exit's calibration check).

Every finished project (at least ``MIN_TASKS`` top-level tasks, all completed) is replayed from
its midpoint: the forecast is computed as of the day halfway between its first task and its last
completion, from what was known that day (``service.compute`` with ``as_of``), and the actual
finish is compared with that forecast's P80 date. A well-calibrated forecast finishes on or
before P80 about 80% of the time; **pass = 70-90%** (P80 ± 10 points, kickoff Q4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.domain.forecasts.service import compute
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject

MIN_TASKS = 10
PASS_LOW, PASS_HIGH = 0.70, 0.90


@dataclass
class Replay:
    project: str
    midpoint: date
    finished: date
    p50: date | None
    p80: date | None
    p95: date | None
    status: str

    @property
    def hit(self) -> bool:
        return self.p80 is not None and self.finished <= self.p80


@dataclass
class Report:
    replays: list[Replay] = field(default_factory=list)

    @property
    def scored(self) -> list[Replay]:
        return [r for r in self.replays if r.status == "ok"]

    @property
    def share(self) -> float:
        scored = self.scored
        return sum(r.hit for r in scored) / len(scored) if scored else 0.0

    @property
    def passed(self) -> bool:
        return bool(self.scored) and PASS_LOW <= self.share <= PASS_HIGH

    def lines(self) -> list[str]:
        out = []
        for r in self.replays:
            if r.status != "ok":
                out.append(f"{r.project}: skipped ({r.status} at {r.midpoint})")
                continue
            mark = "hit " if r.hit else "MISS"
            out.append(
                f"{mark} {r.project}: from {r.midpoint}, finished {r.finished}; "
                f"P50 {r.p50} · P80 {r.p80} · P95 {r.p95}"
            )
        n, hits = len(self.scored), sum(r.hit for r in self.scored)
        out.append(
            f"{hits}/{n} finished on or before P80 = {self.share:.0%} "
            f"(pass: {PASS_LOW:.0%}-{PASS_HIGH:.0%}) -> {'PASS' if self.passed else 'FAIL'}"
        )
        return out


async def backtest(session: AsyncSession, *, runs: int) -> Report:
    finished = (
        select(TaskProject.project_id)
        .join(Task, Task.id == TaskProject.task_id)
        .where(Task.parent_id.is_(None), Task.deleted_at.is_(None))
        .group_by(TaskProject.project_id)
        .having(
            func.count() >= MIN_TASKS,
            func.count().filter(Task.completed_at.is_(None)) == 0,
        )
    )
    projects = list(
        (
            await session.execute(
                select(Project)
                .where(Project.id.in_(finished), Project.deleted_at.is_(None))
                .order_by(Project.name)
            )
        ).scalars()
    )
    report = Report()
    for p in projects:
        first, last = (
            await session.execute(
                select(func.min(Task.created_at), func.max(Task.completed_at))
                .join(TaskProject, TaskProject.task_id == Task.id)
                .where(
                    TaskProject.project_id == p.id,
                    Task.parent_id.is_(None),
                    Task.deleted_at.is_(None),
                )
            )
        ).one()
        start, end = first.astimezone(UTC).date(), last.astimezone(UTC).date()
        mid = start + timedelta(days=(end - start).days // 2)
        r = await compute(session, p, mid, runs=runs)
        report.replays.append(Replay(p.name, mid, end, r.p50, r.p80, r.p95, r.status))
    return report
