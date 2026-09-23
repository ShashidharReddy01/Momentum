"""Transactional outbox. Events are written in the same transaction as the change and
announced with ``pg_notify`` (Postgres only delivers notifications on commit)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.context import Ctx
from momentum.core.db import Base


class EventType(StrEnum):
    USER_JOINED = "user.joined"
    USER_UPDATED = "user.updated"


class OutboxEvent(Base):
    __tablename__ = "events_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID]
    type: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    activity_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_events_outbox_undispatched",
            "id",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
    )


async def emit(
    session: AsyncSession,
    ctx: Ctx,
    *,
    type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    data: dict[str, Any] | None = None,
    channels: list[str] | None = None,
    activity_id: uuid.UUID | None = None,
) -> OutboxEvent | None:
    """Write an outbox row and NOTIFY listeners. No-op in dry-run mode."""
    if ctx.dry_run:
        return None
    payload = {
        "actor": {"id": str(ctx.actor.id) if ctx.actor.id else None, "kind": ctx.actor_kind},
        "channels": channels or [],
        "data": data or {},
        "request_id": ctx.request_id,
    }
    row = OutboxEvent(
        workspace_id=ctx.workspace_id,
        type=type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        activity_id=activity_id,
    )
    session.add(row)
    await session.flush()
    await session.execute(select(func.pg_notify(ctx.settings.events_channel, str(row.id))))
    return row
