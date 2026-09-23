"""Activity log: an immutable record of every change, with an optional undo payload."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.context import Ctx
from momentum.core.db import Base, IdMixin


class Activity(IdMixin, Base):
    __tablename__ = "activity"

    workspace_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_id: Mapped[uuid.UUID | None]
    actor_kind: Mapped[str] = mapped_column(String(16))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID]
    verb: Mapped[str] = mapped_column(String(80))
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    undo_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    ai_action_id: Mapped[uuid.UUID | None]
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_activity_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_activity_workspace_created", "workspace_id", "created_at"),
    )


Diff = dict[str, tuple[Any, Any]]


def jsonable_diff(changes: Diff) -> dict[str, list[Any]]:
    return {k: [_j(old), _j(new)] for k, (old, new) in changes.items()}


def _j(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def record_activity(
    session: AsyncSession,
    ctx: Ctx,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    verb: str,
    changes: Diff | None = None,
    undo: dict[str, Any] | None = None,
    batch_id: uuid.UUID | None = None,
    ai_action_id: uuid.UUID | None = None,
) -> Activity:
    row = Activity(
        workspace_id=ctx.workspace_id,
        actor_id=ctx.actor.id,
        actor_kind=ctx.actor_kind,
        entity_type=entity_type,
        entity_id=entity_id,
        verb=verb,
        diff=jsonable_diff(changes or {}),
        undo_payload=undo,
        batch_id=batch_id,
        ai_action_id=ai_action_id,
        request_id=ctx.request_id,
    )
    session.add(row)
    await session.flush()
    return row
