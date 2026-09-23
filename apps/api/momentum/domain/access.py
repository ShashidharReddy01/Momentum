"""Access rules that need the database (teams, projects, tasks).

Workspace-level rules live in ``momentum.core.permissions``. Everything here follows
docs/architecture/auth-and-permissions.md §4-7. Changes need human approval (CLAUDE.md §6).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound
from momentum.domain.teams.models import Team, TeamMember


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
