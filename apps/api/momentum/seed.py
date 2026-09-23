"""Synthetic seed data (never real company data). Grows each phase."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.ordering import keys_between
from momentum.core.settings import Settings
from momentum.domain.projects.models import Project, ProjectMember
from momentum.domain.sections.models import Section
from momentum.domain.teams.models import Team, TeamMember
from momentum.domain.users.models import User
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
    return {
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
