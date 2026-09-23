"""Access rules that need the database (teams, projects, tasks).

Workspace-level rules live in ``momentum.core.permissions``. Everything here follows
docs/architecture/auth-and-permissions.md §4-7. Changes need human approval (CLAUDE.md §6).
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import ColumnElement, and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

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


async def project_role(session: AsyncSession, ctx: Ctx, project: Project) -> str | None:
    """Effective role: explicit membership wins; otherwise team members are editors on
    team-visible projects and workspace admins are admins of them. Private projects are only
    visible to explicit members (admins included)."""
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
    if project.privacy == "team":
        if ctx.actor.is_admin:
            return "admin"
        if await team_role(session, ctx, project.team_id) is not None:
            return "editor"
    return None


def visible_projects_clause(ctx: Ctx) -> ColumnElement[bool]:
    """SQL predicate for projects the caller can see (use in every project listing)."""
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
        or_(Project.id.in_(explicit), team_visible),
    )


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


async def get_visible_task(
    session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, *, include_deleted: bool = False
) -> tuple[Task, TaskProject | None, str]:
    """Load a task the caller can see with its (primary) placement and the caller's role.

    Visible through any visible project (role = project role); otherwise assignees get editor
    access and creators/followers get commenter access (auth-and-permissions.md §6).
    Subtasks have no placement of their own: they are visible through their top-level task's
    projects, and hidden when any ancestor is deleted.
    """
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
