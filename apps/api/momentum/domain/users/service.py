from __future__ import annotations

import uuid

from sqlalchemy import select
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
