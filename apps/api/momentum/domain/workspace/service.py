from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.ids import new_id
from momentum.core.settings import Settings
from momentum.domain.workspace.models import Workspace


async def get_by_slug(session: AsyncSession, slug: str) -> Workspace | None:
    result = await session.execute(select(Workspace).where(Workspace.slug == slug))
    return result.scalar_one_or_none()


async def ensure_default_workspace(session: AsyncSession, settings: Settings) -> Workspace:
    """Single-workspace mode: return the default workspace, creating it on first use. Safe when
    several first requests arrive at once (insert-or-keep, then read)."""
    ws = await get_by_slug(session, settings.default_workspace_slug)
    if ws is None:
        await session.execute(
            insert(Workspace)
            .values(
                id=new_id(),
                name=settings.default_workspace_name,
                slug=settings.default_workspace_slug,
            )
            .on_conflict_do_nothing(index_elements=["slug"])
        )
        ws = await get_by_slug(session, settings.default_workspace_slug)
        assert ws is not None
    return ws
