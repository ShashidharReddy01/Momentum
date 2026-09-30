"""S6.5.3 ``momentum seed --history``: deterministic synthetic history for the forecast backtest.

About twenty finished (archived) projects over the last six months, in a team **Delivery**,
each generated week by week the way real work goes: a team pace (tasks per
week), a noisy week-to-week rate around it, first in first out, some scope added after the
start, estimates on most tasks, and dependencies whose blockers finish first. Two more projects
are generated the same way but cut off at today, so a forecast has something live to show: one on
track for its due date, one due before it will likely finish. The RNGs are seeded,
so every run (and every machine) gets the same history relative to today. Safe to re-run: a
project that already exists is left alone. Synthetic only.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.ordering import keys_between
from momentum.core.settings import Settings
from momentum.domain.projects.models import Project, ProjectMember
from momentum.domain.sections.models import Section
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import User
from momentum.domain.workspace.service import ensure_default_workspace
from momentum.seed import seed

TEAM = "Delivery"
SEED = 6530
NAMES = [
    "Billing revamp",
    "Onboarding emails",
    "Search relevance",
    "Mobile checkout",
    "Partner portal",
    "Data export",
    "Help center refresh",
    "SSO for enterprise",
    "Pricing experiment",
    "Status page",
    "Referral program",
    "Accessibility pass",
    "Invoice PDFs",
    "Usage dashboard",
    "Team permissions",
    "API rate limits",
    "Localization (German)",
    "Audit log",
    "Webhooks v2",
    "Churn survey",
]
ESTIMATES = [60, 120, 120, 180, 240, 240, 360, 480]
WINDOW_DAYS = 185  # every project finished within about six months
# in flight today: (name, due date as a share of the generated length: <1 means due too early)
ACTIVE = [("Customer portal", 1.25), ("Mobile onboarding", 0.8)]


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _at(day: date, rng: random.Random) -> datetime:
    return datetime.combine(day, time(rng.randint(9, 17), rng.randint(0, 59)), tzinfo=UTC)


def _plan(rng: random.Random) -> tuple[int, list[tuple[int, int | None]], int]:
    """(planned weeks, [(created_day, completed_day)] relative to the start, finish day)."""
    weeks = rng.randint(6, 14)
    pace = rng.uniform(2.5, 7.0)
    initial = max(8, round(pace * weeks))
    growth = round(initial * rng.uniform(0.0, 0.15))
    created = [0] * initial + sorted(rng.randint(1, int(weeks * 7 * 0.7)) for _ in range(growth))
    done: list[int | None] = [None] * len(created)
    week = 0
    while any(d is None for d in done) and week < 200:
        end = week * 7 + 6
        ready = [i for i, d in enumerate(done) if d is None and created[i] <= end]
        n = min(len(ready), _poisson(rng, pace * rng.uniform(0.4, 1.6)))
        for i in ready[:n]:  # first in, first out
            done[i] = max(created[i], week * 7 + rng.randint(0, 6))
        week += 1
    finish = max(d for d in done if d is not None)
    return weeks, list(zip(created, done, strict=True)), finish


async def _project(
    session: AsyncSession,
    ws: Any,
    team: Team,
    owner: User,
    name: str,
    color: str,
    start: date,
    due: date,
    archived_at: datetime | None,
) -> tuple[Project, Section] | None:
    """A new project with one section, or ``None`` when it already exists (safe to re-run)."""
    if (
        await session.execute(
            select(Project.id).where(Project.workspace_id == ws.id, Project.name == name)
        )
    ).first() is not None:
        return None
    project = Project(
        workspace_id=ws.id,
        team_id=team.id,
        name=name,
        color=color,
        privacy="team",
        owner_id=owner.id,
        created_by=owner.id,
        created_via="import",
        start_on=start,
        due_on=due,
        status="complete" if archived_at else None,
        archived_at=archived_at,
    )
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="admin"))
    section = Section(
        workspace_id=ws.id,
        project_id=project.id,
        name="Work",
        position=keys_between(None, None, 1)[0],
    )
    session.add(section)
    await session.flush()
    return project, section


async def _tasks(
    session: AsyncSession,
    ws: Any,
    owner: User,
    project: Project,
    section: Section,
    base: str,
    start: date,
    tasks: list[tuple[int, int | None]],
    rng: random.Random,
) -> tuple[int, int]:
    """Add the tasks (created/completed days relative to ``start``) with estimates and
    dependencies whose blockers finish first. Returns (tasks, dependencies)."""
    estimates = [rng.choice(ESTIMATES) if rng.random() < 0.9 else None for _ in tasks]
    order = [d if d is not None else 10**6 for _c, d in tasks]
    blockers = {
        j: rng.choice(earlier)
        for j in range(len(tasks))
        if rng.random() < 0.15 and (earlier := [k for k in range(j) if order[k] <= order[j]])
    }
    rows: list[Task] = []
    for (made, done), est, pos in zip(
        tasks, estimates, keys_between(None, None, len(tasks)), strict=True
    ):
        ws.task_seq += 1
        t = Task(
            workspace_id=ws.id,
            number=ws.task_seq,
            title=f"{base}: step {len(rows) + 1}",
            assignee_id=owner.id,
            created_at=_at(start + timedelta(days=made), rng),
            completed_at=_at(start + timedelta(days=done), rng) if done is not None else None,
            completed_by=owner.id if done is not None else None,
            estimate_minutes=est,
            created_by=owner.id,
            created_via="import",
        )
        session.add(t)
        await session.flush()
        session.add(
            TaskProject(task_id=t.id, project_id=project.id, section_id=section.id, position=pos)
        )
        rows.append(t)
    for j, k in blockers.items():
        session.add(TaskDependency(task_id=rows[j].id, depends_on_id=rows[k].id))
    await session.flush()
    return len(rows), len(blockers)


async def seed_history(session: AsyncSession, settings: Settings) -> dict[str, int]:
    await seed(session, settings)
    ws = await ensure_default_workspace(session, settings)
    owner = (
        await session.execute(
            select(User).where(User.workspace_id == ws.id, User.email.startswith("ravi@"))
        )
    ).scalar_one()
    team = (
        await session.execute(select(Team).where(Team.workspace_id == ws.id, Team.name == TEAM))
    ).scalar_one_or_none()
    if team is None:
        team = Team(workspace_id=ws.id, name=TEAM, created_by=owner.id, color="proj-10")
        session.add(team)
        await session.flush()
        session.add(TeamMember(team_id=team.id, user_id=owner.id, role="lead"))
    today = datetime.now(UTC).date()
    out = {
        "history_projects": 0,
        "history_tasks": 0,
        "history_dependencies": 0,
        "active_projects": 0,
    }
    for i, base in enumerate(NAMES):
        # each project draws from its own seeded sequence, so it comes out the same whether or
        # not the others already exist
        rng = random.Random(f"{SEED}:{i}")  # noqa: S311 - deterministic synthetic data
        weeks, tasks, finish = _plan(rng)
        # place it: finished between 1 day and the window's end ago
        latest_start = today - timedelta(days=finish + 1)
        start = latest_start - timedelta(days=rng.randint(0, max(0, WINDOW_DAYS - finish - 1)))
        made = await _project(
            session,
            ws,
            team,
            owner,
            f"H{i + 1:02d} · {base}",
            f"proj-{i % 12 + 1}",
            start,
            start + timedelta(days=weeks * 7),
            _at(start + timedelta(days=finish + 1), rng),
        )
        if made is None:
            continue
        n, deps = await _tasks(session, ws, owner, *made, base, start, tasks, rng)
        out["history_projects"] += 1
        out["history_tasks"] += n
        out["history_dependencies"] += deps
    for k, (base, due_share) in enumerate(ACTIVE):
        live = random.Random(f"{SEED}:live:{k}")  # noqa: S311 - deterministic synthetic data
        _weeks, tasks, finish = _plan(live)
        elapsed = finish // 2  # halfway through today
        start = today - timedelta(days=elapsed)
        cut = [(c, d if d is not None and d <= elapsed else None) for c, d in tasks if c <= elapsed]
        made = await _project(
            session,
            ws,
            team,
            owner,
            base,
            "proj-6" if due_share >= 1 else "proj-1",
            start,
            start + timedelta(days=round(finish * due_share)),
            None,
        )
        if made is None:
            continue
        await _tasks(session, ws, owner, *made, base, start, cut, live)
        out["active_projects"] += 1
    return out
