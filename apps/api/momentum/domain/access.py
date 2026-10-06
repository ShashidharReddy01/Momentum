"""Access rules that need the database (teams, projects, tasks).

Workspace-level rules live in ``momentum.core.permissions``. Everything here follows
docs/architecture/auth-and-permissions.md §4-7. Changes need human approval (CLAUDE.md §6).
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import ColumnElement, and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound
from momentum.domain.projects.models import Project, ProjectMember
from momentum.domain.tasks.models import Follower, Task, TaskProject
from momentum.domain.teams.models import Team, TeamMember

ProjectRole = Literal["admin", "editor", "commenter", "viewer"]
ROLE_RANK: dict[str, int] = {"viewer": 0, "commenter": 1, "editor": 2, "admin": 3}


async def team_role(session: AsyncSession, ctx: Ctx, team_id: uuid.UUID) -> str | None:
    """The caller's role in a team: 'lead', 'member', or None."""
    if ctx.actor.id is None:
        return None
    return (
        await session.execute(
            select(TeamMember.role).where(
                TeamMember.team_id == team_id, TeamMember.user_id == ctx.actor.id
            )
        )
    ).scalar_one_or_none()


async def get_visible_team(session: AsyncSession, ctx: Ctx, team_id: uuid.UUID) -> Team:
    """Load a team the caller may see (members and admins); otherwise NotFound."""
    team = await session.get(Team, team_id)
    if team is None or team.deleted_at is not None or team.workspace_id != ctx.workspace_id:
        raise NotFound("Team not found")
    if not ctx.actor.is_admin and await team_role(session, ctx, team_id) is None:
        raise NotFound("Team not found")
    return team


async def require_team_manager(session: AsyncSession, ctx: Ctx, team: Team) -> None:
    """Leads and workspace admins manage a team."""
    if ctx.actor.is_admin:
        return
    if await team_role(session, ctx, team.id) != "lead":
        raise Forbidden("Only team leads or admins can change this team")


# ---------------- projects ----------------


def _for(ctx: Ctx) -> Ctx | None:
    """S5.1.3 (product owner, 2026-09-29): an agent working for a person who asked (assigned,
    @mentioned, run now) carries that person in ``ctx.acting_for``. It then sees only what
    **both** can see, with the lower of the two roles, so it can't pass on content the person
    couldn't reach, nor change what they couldn't change."""
    if ctx.acting_for is None:
        return None
    return ctx.with_(actor=ctx.acting_for, acting_for=None)


def _lower(a: str, b: str) -> str:
    return a if ROLE_RANK[a] <= ROLE_RANK[b] else b


async def project_role(session: AsyncSession, ctx: Ctx, project: Project) -> str | None:
    """Effective role: explicit membership wins; otherwise team members are editors on
    team-visible projects and workspace admins are admins of them. Private projects are only
    visible to explicit members (admins included). Agents only ever have explicit roles. With
    ``ctx.acting_for``, the lower of both roles, and none unless both have one."""
    role = await _own_project_role(session, ctx, project)
    other = _for(ctx)
    if role is None or other is None:
        return role
    theirs = await _own_project_role(session, other, project)
    return None if theirs is None else _lower(role, theirs)


async def _own_project_role(session: AsyncSession, ctx: Ctx, project: Project) -> str | None:
    if ctx.actor.id is None:
        return None
    explicit = (
        await session.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project.id, ProjectMember.user_id == ctx.actor.id
            )
        )
    ).scalar_one_or_none()
    if explicit is not None:
        return explicit
    if _explicit_only(ctx):
        # S5.1.1 (kickoff Q1): an agent sees only projects its account was explicitly given,
        # never through team membership or an admin role. So does a guest (E7.0, H61:
        # auth-and-permissions.md §4 "only explicitly shared projects").
        return None
    if project.privacy == "team":
        if ctx.actor.is_admin:
            return "admin"
        if await team_role(session, ctx, project.team_id) is not None:
            return "editor"
    return None


async def project_roles(
    session: AsyncSession, ctx: Ctx, projects: list[Project]
) -> dict[uuid.UUID, str | None]:
    """``project_role`` for many projects in two queries (Phase 7.5: a portfolio's rows say which
    projects the viewer may edit). Same rules, including ``acting_for``."""

    async def own(c: Ctx) -> dict[uuid.UUID, str | None]:
        if c.actor.id is None:
            return {p.id: None for p in projects}
        ids = [p.id for p in projects]
        rows = await session.execute(
            select(ProjectMember.project_id, ProjectMember.role).where(
                ProjectMember.project_id.in_(ids), ProjectMember.user_id == c.actor.id
            )
        )
        explicit = {pid: role for pid, role in rows.tuples()}
        teams = set(
            (
                await session.execute(
                    select(TeamMember.team_id).where(TeamMember.user_id == c.actor.id)
                )
            ).scalars()
        )
        out: dict[uuid.UUID, str | None] = {}
        for p in projects:
            if p.id in explicit:
                out[p.id] = explicit[p.id]
            elif _explicit_only(c) or p.privacy != "team":
                out[p.id] = None
            elif c.actor.is_admin:
                out[p.id] = "admin"
            else:
                out[p.id] = "editor" if p.team_id in teams else None
        return out

    mine = await own(ctx)
    other = _for(ctx)
    if other is None:
        return mine
    theirs = await own(other)
    return {
        pid: None if r is None or theirs.get(pid) is None else _lower(r, theirs[pid])  # type: ignore[arg-type]
        for pid, r in mine.items()
    }


def visible_projects_clause(ctx: Ctx) -> ColumnElement[bool]:
    """SQL predicate for projects the caller can see (use in every project listing). With
    ``ctx.acting_for``, only projects both can see."""
    other = _for(ctx)
    if other is not None:
        return and_(_own_projects_clause(ctx), _own_projects_clause(other))
    return _own_projects_clause(ctx)


def _own_projects_clause(ctx: Ctx) -> ColumnElement[bool]:
    explicit = select(ProjectMember.project_id).where(ProjectMember.user_id == ctx.actor.id)
    live_teams = select(Team.id).where(
        Team.workspace_id == ctx.workspace_id, Team.deleted_at.is_(None)
    )
    my_teams = select(TeamMember.team_id).where(TeamMember.user_id == ctx.actor.id)
    team_visible = and_(
        Project.privacy == "team",
        true() if ctx.actor.is_admin else Project.team_id.in_(my_teams),
    )
    return and_(
        Project.workspace_id == ctx.workspace_id,
        Project.deleted_at.is_(None),
        Project.team_id.in_(live_teams),
        # agents and guests: explicit membership only (project_role says the same)
        Project.id.in_(explicit)
        if _explicit_only(ctx)
        else or_(Project.id.in_(explicit), team_visible),
    )


def _explicit_only(ctx: Ctx) -> bool:
    return ctx.actor.is_agent or ctx.actor.role == "guest"


def visible_people_clause(
    ctx: Ctx, user_id: ColumnElement[uuid.UUID] | InstrumentedAttribute[uuid.UUID]
) -> ColumnElement[bool]:
    """People the caller may see in pickers, the directory, @mentions and workload: everyone for
    members and admins; for a guest (E7.0, H61) only themselves and the people of the projects
    shared with them (explicit members, and the team of a team-visible one)."""
    if ctx.actor.role != "guest":
        return true()
    shared = select(ProjectMember.project_id).where(ProjectMember.user_id == ctx.actor.id)
    members = select(ProjectMember.user_id).where(ProjectMember.project_id.in_(shared))
    teams = (
        select(TeamMember.user_id)
        .join(Project, Project.team_id == TeamMember.team_id)
        .where(Project.id.in_(shared), Project.privacy == "team")
    )
    return or_(user_id == ctx.actor.id, user_id.in_(members), user_id.in_(teams))


async def get_visible_project(
    session: AsyncSession, ctx: Ctx, project_id: uuid.UUID, *, include_deleted: bool = False
) -> tuple[Project, str]:
    """Load a project the caller can see, with the caller's role; otherwise NotFound."""
    project = await session.get(Project, project_id)
    if (
        project is None
        or project.workspace_id != ctx.workspace_id
        or (project.deleted_at is not None and not include_deleted)
    ):
        raise NotFound("Project not found")
    team = await session.get(Team, project.team_id)
    if team is None or team.deleted_at is not None:
        raise NotFound("Project not found")
    role = await project_role(session, ctx, project)
    if role is None:
        raise NotFound("Project not found")
    return project, role


def forbid_agent(ctx: Ctx, what: str) -> None:
    """agents.md §3: agents never delete and never decide approvals (S5.1.2). Enforced in the
    services, since the model is never the security boundary; a person applying or undoing an
    agent's change acts as themselves and isn't affected."""
    if ctx.actor.is_agent:
        raise Forbidden(f"Agents can't {what}")


def require_project_role(role: str, needed: str, what: str = "do this") -> None:
    if ROLE_RANK[role] < ROLE_RANK[needed]:
        raise Forbidden(f"You need {needed} access to {what}")


# ---------------- tasks ----------------


MAX_TASK_DEPTH = 5


async def task_ancestors(session: AsyncSession, task: Task) -> list[Task]:
    """Parent, grandparent, … up to the top-level task (bounded; cycles are impossible by
    construction but the walk is capped anyway)."""
    chain: list[Task] = []
    current = task
    while current.parent_id is not None and len(chain) <= MAX_TASK_DEPTH + 1:
        parent = await session.get(Task, current.parent_id)
        if parent is None:
            break
        chain.append(parent)
        current = parent
    return chain


async def ancestors_of(session: AsyncSession, tasks: list[Task]) -> dict[uuid.UUID, list[Task]]:
    """``task_ancestors`` for many tasks at once: one query per nesting level for the whole set
    (at most MAX_TASK_DEPTH + 1), instead of one query per parent per task. Each list runs from
    the parent up to the top-level task; top-level tasks map to an empty list."""
    known: dict[uuid.UUID, Task] = {t.id: t for t in tasks}
    wanted = {t.parent_id for t in tasks if t.parent_id is not None} - set(known)
    for _ in range(MAX_TASK_DEPTH + 2):
        if not wanted:
            break
        rows = (await session.execute(select(Task).where(Task.id.in_(wanted)))).scalars().all()
        for row in rows:
            known[row.id] = row
        wanted = {r.parent_id for r in rows if r.parent_id is not None} - set(known)
    out: dict[uuid.UUID, list[Task]] = {}
    for t in tasks:
        chain: list[Task] = []
        current = t
        while current.parent_id is not None and len(chain) <= MAX_TASK_DEPTH + 1:
            parent = known.get(current.parent_id)
            if parent is None:
                break
            chain.append(parent)
            current = parent
        out[t.id] = chain
    return out


async def get_visible_task(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, *, include_deleted: bool = False
) -> tuple[Task, TaskProject | None, str]:
    """Load a task the caller can see with its (primary) placement and the caller's role.

    Visible through any visible project (role = project role); otherwise assignees get editor
    access and creators/followers get commenter access (auth-and-permissions.md §6).
    Subtasks have no placement of their own: they are visible through their top-level task's
    projects, and hidden when any ancestor is deleted. With ``ctx.acting_for``, the task must be
    visible to both, and the role is the lower of the two.
    """
    other = _for(ctx)
    if other is None:
        return await _own_visible_task(session, ctx, task_id, include_deleted)
    mine_ctx = ctx.with_(acting_for=None)
    task, placement, role = await _own_visible_task(session, mine_ctx, task_id, include_deleted)
    _t, _p, theirs = await _own_visible_task(session, other, task_id, include_deleted)
    return task, placement, _lower(role, theirs)


async def _own_visible_task(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, include_deleted: bool
) -> tuple[Task, TaskProject | None, str]:
    task = await session.get(Task, task_id)
    if (
        task is None
        or task.workspace_id != ctx.workspace_id
        or (task.deleted_at is not None and not include_deleted)
    ):
        raise NotFound("Task not found")
    ancestors = await task_ancestors(session, task)
    if any(a.deleted_at is not None for a in ancestors):
        raise NotFound("Task not found")
    root = ancestors[-1] if ancestors else task
    placements = (
        (await session.execute(select(TaskProject).where(TaskProject.task_id == root.id)))
        .scalars()
        .all()
    )
    best: tuple[TaskProject | None, str | None] = (placements[0] if placements else None, None)
    for pl in placements:
        project = await session.get(Project, pl.project_id)
        if project is None or project.deleted_at is not None:
            continue
        role = await project_role(session, ctx, project)
        if role is not None and (best[1] is None or ROLE_RANK[role] > ROLE_RANK[best[1]]):
            best = (pl, role)
    if best[1] is not None:
        return task, best[0], best[1]
    if ctx.actor.id is not None and task.assignee_id == ctx.actor.id:
        return task, best[0], "editor"
    # personal access (follower/creator of the task, or assignee/follower of an ancestor)
    chain_ids = [task.id, *(a.id for a in ancestors)]
    is_follower = (
        await session.execute(
            select(Follower.user_id).where(
                Follower.task_id.in_(chain_ids), Follower.user_id == ctx.actor.id
            )
        )
    ).first() is not None
    related = ctx.actor.id is not None and (
        task.created_by == ctx.actor.id or any(a.assignee_id == ctx.actor.id for a in ancestors)
    )
    if is_follower or related:
        return task, best[0], "commenter"
    raise NotFound("Task not found")
