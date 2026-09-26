"""Synthetic seed data (never real company data). Grows each phase."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.ordering import keys_between
from momentum.core.settings import Settings
from momentum.domain.projects.models import Project, ProjectMember
from momentum.domain.sections.models import Section
from momentum.domain.tasks.models import Follower, Task, TaskProject
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import User
from momentum.domain.workspace.models import Workspace
from momentum.domain.workspace.service import ensure_default_workspace

SEED_DOMAIN = "acme-demo.test"

SEED_USERS: list[tuple[str, str, str, str]] = [
    # (name, local-part, role, timezone)
    ("Avery Admin", "admin", "admin", "Europe/London"),
    ("Ravi Kumar", "ravi", "member", "Asia/Kolkata"),
    ("Ana Souza", "ana", "member", "America/Sao_Paulo"),
    ("Priya Nair", "priya", "member", "Asia/Kolkata"),
    ("Tom Becker", "tom", "member", "Europe/Berlin"),
    ("Mei Chen", "mei", "member", "Asia/Singapore"),
    ("Jordan Lee", "jordan", "member", "America/New_York"),
    ("Sam Okafor", "sam", "member", "Africa/Lagos"),
    ("Lena Novak", "lena", "member", "Europe/Prague"),
    ("Diego Ruiz", "diego", "member", "Europe/Madrid"),
    ("Kim Park", "kim", "member", "Asia/Seoul"),
    ("Noor Haddad", "noor", "member", "Asia/Dubai"),
]


async def seed(session: AsyncSession, settings: Settings) -> dict[str, int]:
    ws = await ensure_default_workspace(session, settings)
    if ws.name == settings.default_workspace_name:
        ws.name = "Acme Demo"
    created = 0
    for name, local, role, tz in SEED_USERS:
        email = f"{local}@{SEED_DOMAIN}"
        exists = await session.execute(
            select(User.id).where(User.workspace_id == ws.id, User.email == email)
        )
        if exists.scalar_one_or_none() is None:
            session.add(User(workspace_id=ws.id, email=email, name=name, role=role, timezone=tz))
            created += 1
    await session.flush()
    teams_created = await _seed_teams(session, ws.id)
    projects_created = await _seed_projects(session, ws.id)
    tasks_created = await _seed_tasks(session, ws)
    return {
        "tasks_created": tasks_created,
        "users_created": created,
        "teams_created": teams_created,
        "projects_created": projects_created,
    }


# (team, project, color, privacy, owner local-part, explicit members, sections)
SEED_PROJECTS: list[tuple[str, str, str, str, str, list[str], list[str]]] = [
    (
        "Product",
        "Website Revamp",
        "proj-6",
        "team",
        "ravi",
        [],
        ["Backlog", "In progress", "Review", "Done"],
    ),
    (
        "Product",
        "Mobile App v2",
        "proj-8",
        "private",
        "priya",
        ["ravi"],
        ["To do", "Doing", "Done"],
    ),
    (
        "Marketing",
        "Q4 Launch Campaign",
        "proj-1",
        "team",
        "ana",
        [],
        ["Planning", "Content", "Launch"],
    ),
    (
        "Operations",
        "Vendor Onboarding",
        "proj-4",
        "team",
        "jordan",
        [],
        ["Requests", "In review", "Approved"],
    ),
]


async def _seed_projects(session: AsyncSession, workspace_id: object) -> int:
    users = {
        u.email.split("@")[0]: u
        for u in (
            await session.execute(select(User).where(User.workspace_id == workspace_id))
        ).scalars()
    }
    teams = {
        t.name: t
        for t in (
            await session.execute(select(Team).where(Team.workspace_id == workspace_id))
        ).scalars()
    }
    created = 0
    for team, name, color, privacy, owner, members, sections in SEED_PROJECTS:
        if team not in teams or owner not in users:
            continue
        exists = await session.execute(
            select(Project.id).where(Project.workspace_id == workspace_id, Project.name == name)
        )
        if exists.scalar_one_or_none() is not None:
            continue
        project = Project(
            workspace_id=workspace_id,
            team_id=teams[team].id,
            name=name,
            color=color,
            privacy=privacy,
            owner_id=users[owner].id,
            created_by=users[owner].id,
            created_via="import",
        )
        session.add(project)
        await session.flush()
        session.add(ProjectMember(project_id=project.id, user_id=users[owner].id, role="admin"))
        for m in members:
            session.add(ProjectMember(project_id=project.id, user_id=users[m].id, role="editor"))
        for sec, pos in zip(sections, keys_between(None, None, len(sections)), strict=True):
            session.add(
                Section(workspace_id=workspace_id, project_id=project.id, name=sec, position=pos)
            )
        created += 1
    await session.flush()
    return created


# (team name, color token, lead local-part, member local-parts)
SEED_TEAMS: list[tuple[str, str, str, list[str]]] = [
    ("Product", "proj-7", "ravi", ["ana", "priya", "mei", "admin"]),
    ("Marketing", "proj-2", "ana", ["tom", "lena", "noor"]),
    ("Operations", "proj-4", "jordan", ["sam", "diego", "kim", "ravi"]),
]


async def _seed_teams(session: AsyncSession, workspace_id: object) -> int:
    users = {
        u.email.split("@")[0]: u
        for u in (
            await session.execute(select(User).where(User.workspace_id == workspace_id))
        ).scalars()
    }
    created = 0
    for name, color, lead, members in SEED_TEAMS:
        exists = await session.execute(
            select(Team.id).where(Team.workspace_id == workspace_id, Team.name == name)
        )
        if exists.scalar_one_or_none() is not None or lead not in users:
            continue
        team = Team(workspace_id=workspace_id, name=name, color=color, created_by=users[lead].id)
        session.add(team)
        await session.flush()
        session.add(TeamMember(team_id=team.id, user_id=users[lead].id, role="lead"))
        for m in members:
            if m in users:
                session.add(TeamMember(team_id=team.id, user_id=users[m].id, role="member"))
        created += 1
    await session.flush()
    return created


SEED_TASKS: dict[str, list[str]] = {
    "Website Revamp": [
        "Audit current site analytics",
        "Collect competitor pricing pages",
        "Draft new information architecture",
        "Write homepage hero copy",
        "Design pricing page mockups",
        "Review mockups with Ana",
        "Set up staging environment",
        "Migrate blog posts",
        "Accessibility audit",
        "Performance budget for landing pages",
        "Update footer links",
        "Plan launch announcement",
    ],
    "Mobile App v2": [
        "Define v2 scope",
        "Offline mode spike",
        "Push notification settings",
        "Crash reporting setup",
        "Beta tester recruitment",
        "App store screenshots",
    ],
    "Q4 Launch Campaign": [
        "Campaign brief",
        "Budget approval",
        "Landing page copy",
        "Email sequence (3 emails)",
        "Social calendar",
        "Press list",
        "Webinar outline",
        "Customer quotes",
    ],
    "Vendor Onboarding": [
        "Security questionnaire: Acme Cloud",
        "Contract review: DataCo",
        "Tax forms: PrintHub",
        "Kickoff call: Acme Cloud",
        "Access provisioning: DataCo",
    ],
}


async def _seed_tasks(session: AsyncSession, ws: Workspace) -> int:
    rng = random.Random(42)  # noqa: S311 - deterministic synthetic data, not security
    # ordered: the fixed-seed rng below must see users in the same order every run, or seeded
    # assignments (and anything a journey reads from them) change between runs
    users = list(
        (
            await session.execute(
                select(User).where(User.workspace_id == ws.id).order_by(User.email)
            )
        ).scalars()
    )
    today = date.today()
    created = 0
    for project_name, titles in SEED_TASKS.items():
        project = (
            await session.execute(
                select(Project).where(Project.workspace_id == ws.id, Project.name == project_name)
            )
        ).scalar_one_or_none()
        if project is None:
            continue
        has_tasks = await session.execute(
            select(TaskProject.task_id).where(TaskProject.project_id == project.id).limit(1)
        )
        if has_tasks.first() is not None:
            continue
        sections = list(
            (
                await session.execute(
                    select(Section)
                    .where(Section.project_id == project.id)
                    .order_by(Section.position)
                )
            ).scalars()
        )
        per_section: dict[uuid.UUID, list[str]] = {s.id: [] for s in sections}
        for i, title in enumerate(titles):
            per_section[
                sections[min(i * len(sections) // len(titles), len(sections) - 1)].id
            ].append(title)
        for section in sections:
            names = per_section[section.id]
            for title, pos in zip(names, keys_between(None, None, len(names)), strict=True):
                ws.task_seq += 1
                assignee = rng.choice(users) if rng.random() < 0.8 else None
                due = today + timedelta(days=rng.randint(-5, 21)) if rng.random() < 0.7 else None
                done = section is sections[-1] and rng.random() < 0.6
                task = Task(
                    workspace_id=ws.id,
                    number=ws.task_seq,
                    title=title,
                    assignee_id=assignee.id if assignee else None,
                    due_on=due,
                    completed_at=datetime.now(UTC) - timedelta(days=rng.randint(0, 6))
                    if done
                    else None,
                    created_by=project.owner_id,
                    created_via="import",
                )
                session.add(task)
                await session.flush()
                session.add(
                    TaskProject(
                        task_id=task.id, project_id=project.id, section_id=section.id, position=pos
                    )
                )
                for uid in {project.owner_id, task.assignee_id} - {None}:
                    session.add(Follower(task_id=task.id, user_id=uid))
                created += 1
    await session.flush()
    return created


PERF_PROJECT = "Load Test (2k)"
PERF_SECTIONS = ["Inbox", "Planned", "In progress", "Review", "Done"]
_WORDS = [
    "update",
    "review",
    "draft",
    "fix",
    "plan",
    "audit",
    "sync",
    "design",
    "test",
    "ship",
    "migrate",
    "refactor",
    "document",
    "prepare",
    "check",
    "verify",
    "clean",
    "polish",
    "measure",
    "publish",
    "analyse",
]
_THINGS = [
    "homepage",
    "copy",
    "invoice",
    "flow",
    "onboarding",
    "email",
    "pricing",
    "table",
    "API",
    "client",
    "release",
    "notes",
    "search",
    "index",
    "billing",
    "page",
    "vendor",
    "list",
    "roadmap",
    "slide",
    "QA",
    "checklist",
    "style",
    "guide",
]


async def seed_perf(session: AsyncSession, settings: Settings, n: int = 2000) -> dict[str, int]:
    """A large synthetic project for performance work (S1.2.6). Safe to re-run."""
    await seed(session, settings)
    ws = await ensure_default_workspace(session, settings)
    exists = await session.execute(
        select(Project.id).where(Project.workspace_id == ws.id, Project.name == PERF_PROJECT)
    )
    if exists.scalar_one_or_none() is not None:
        return {"perf_tasks_created": 0}
    # ordered: the fixed-seed rng below must see users in the same order every run, or seeded
    # assignments (and anything a journey reads from them) change between runs
    users = list(
        (
            await session.execute(
                select(User).where(User.workspace_id == ws.id).order_by(User.email)
            )
        ).scalars()
    )
    owner = next(u for u in users if u.email.startswith("ravi@"))
    team = (
        await session.execute(
            select(Team).where(Team.workspace_id == ws.id, Team.name == "Product")
        )
    ).scalar_one()
    project = Project(
        workspace_id=ws.id,
        team_id=team.id,
        name=PERF_PROJECT,
        color="proj-10",
        privacy="team",
        owner_id=owner.id,
        created_by=owner.id,
        created_via="import",
    )
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="admin"))
    sections = [
        Section(workspace_id=ws.id, project_id=project.id, name=name, position=pos)
        for name, pos in zip(
            PERF_SECTIONS, keys_between(None, None, len(PERF_SECTIONS)), strict=True
        )
    ]
    session.add_all(sections)
    await session.flush()
    rng = random.Random(7)  # noqa: S311 (synthetic data)
    today = datetime.now(UTC).date()
    per = n // len(sections)
    for s_index, section in enumerate(sections):
        count = per if s_index < len(sections) - 1 else n - per * (len(sections) - 1)
        for pos in keys_between(None, None, count):
            ws.task_seq += 1
            assignee = rng.choice(users) if rng.random() < 0.75 else None
            task = Task(
                workspace_id=ws.id,
                number=ws.task_seq,
                title=f"{rng.choice(_WORDS).capitalize()} {rng.choice(_THINGS)} #{ws.task_seq}",
                assignee_id=assignee.id if assignee else None,
                due_on=today + timedelta(days=rng.randint(-10, 40)) if rng.random() < 0.6 else None,
                created_by=owner.id,
                created_via="import",
            )
            session.add(task)
            await session.flush()
            session.add(
                TaskProject(
                    task_id=task.id, project_id=project.id, section_id=section.id, position=pos
                )
            )
    await session.flush()
    return {"perf_tasks_created": n}
