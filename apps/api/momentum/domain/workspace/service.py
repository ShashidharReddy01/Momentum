from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.settings import Settings
from momentum.domain.workspace.models import Workspace


async def get_by_slug(session: AsyncSession, slug: str) -> Workspace | None:
    result = await session.execute(select(Workspace).where(Workspace.slug == slug))
    return result.scalar_one_or_none()


async def ensure_default_workspace(session: AsyncSession, settings: Settings) -> Workspace:
    """Single-workspace mode: return the default workspace, creating it on first use."""
    ws = await get_by_slug(session, settings.default_workspace_slug)
    if ws is None:
        ws = Workspace(name=settings.default_workspace_name, slug=settings.default_workspace_slug)
        session.add(ws)
        await session.flush()
    return ws
