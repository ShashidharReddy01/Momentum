from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import NotFound
from momentum.domain.users.models import User
from momentum.domain.workspace.models import Workspace


async def get_me(session: AsyncSession, ctx: Ctx) -> tuple[User, Workspace]:
    user = await session.get(User, ctx.actor.id)
    workspace = await session.get(Workspace, ctx.workspace_id)
    if user is None or workspace is None:
        raise NotFound()
    return user, workspace


async def list_dev_login_users(session: AsyncSession, workspace_id: uuid.UUID) -> list[User]:
    """Users offered on the dev login page (dev modes only)."""
    result = await session.execute(
        select(User)
        .where(
            User.workspace_id == workspace_id, User.status != "disabled", User.is_agent.is_(False)
        )
        .order_by(User.role, User.name)
    )
    return list(result.scalars())


async def list_users(
    session: AsyncSession,
    ctx: Ctx,
    *,
    q: str | None = None,
    limit: int = 50,
    include_agents: bool = False,
) -> list[User]:
    """Active workspace members for pickers, optionally filtered by name/email prefix."""
    query = select(User).where(User.workspace_id == ctx.workspace_id, User.status != "disabled")
    if not include_agents:
        query = query.where(User.is_agent.is_(False))
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(
            (func.lower(User.name).like(like)) | (func.lower(User.email).like(like))
        )
    result = await session.execute(query.order_by(func.lower(User.name)).limit(min(limit, 200)))
    return list(result.scalars())
