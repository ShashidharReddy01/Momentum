"""Phase 7.5 (spec §9.1): when a person last looked at Home, a project or a portfolio, so "Catch me
up" knows what changed since. Like view preferences and read markers, a visit is the person's own
reading state: no activity row, no event (D75-70). The client writes it on leaving a page or after
30 s on it; the server writes at most once per scope per 5 minutes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, ValidationFailed
from momentum.domain.access import get_visible_project
from momentum.domain.dashboards.models import UserVisit

Scope = Literal["home", "project", "portfolio"]
DEBOUNCE = timedelta(minutes=5)


async def check_scope(
    session: AsyncSession, ctx: Ctx, scope: Scope, scope_id: uuid.UUID | None
) -> None:
    """The scope exists and the person can see it (Home has no id)."""
    if scope == "home":
        if scope_id is not None:
            raise ValidationFailed("Home has no scope id")
        return
    if scope_id is None:
        raise ValidationFailed(f"Say which {scope}")
    if scope == "project":
        await get_visible_project(session, ctx, scope_id)
    else:
        from momentum.domain.portfolios.service import get_portfolio

        await get_portfolio(session, ctx, scope_id)


async def _row(
    session: AsyncSession, ctx: Ctx, scope: Scope, scope_id: uuid.UUID | None
) -> UserVisit | None:
    q = select(UserVisit).where(
        UserVisit.user_id == ctx.actor.id,
        UserVisit.scope_type == scope,
        UserVisit.scope_id.is_(None) if scope_id is None else UserVisit.scope_id == scope_id,
    )
    return (await session.execute(q)).scalar_one_or_none()


async def last_seen(
    session: AsyncSession, ctx: Ctx, scope: Scope, scope_id: uuid.UUID | None
) -> datetime | None:
    if ctx.actor.id is None:
        return None
    row = await _row(session, ctx, scope, scope_id)
    return row.last_seen_at if row is not None else None


async def record_visit(
    session: AsyncSession,
    ctx: Ctx,
    scope: Scope,
    scope_id: uuid.UUID | None,
    *,
    now: datetime | None = None,
) -> datetime:
    """Mark the scope seen now (at most one write per scope per 5 minutes)."""
    if ctx.actor.id is None or ctx.actor.is_agent:
        raise Forbidden("Only people have visits")
    await check_scope(session, ctx, scope, scope_id)
    now = now or datetime.now(UTC)
    row = await _row(session, ctx, scope, scope_id)
    if row is None:
        row = UserVisit(
            user_id=ctx.actor.id,
            workspace_id=ctx.workspace_id,
            scope_type=scope,
            scope_id=scope_id,
            last_seen_at=now,
        )
        session.add(row)
    elif now - row.last_seen_at >= DEBOUNCE:
        row.last_seen_at = now
    await session.flush()
    return row.last_seen_at
