"""Turns new events_outbox rows into Hub publishes.

Each app process tracks its own ``after_id`` cursor (in memory, seeded from ``max(id)`` at
startup by listener.py) and re-reads every row above it — never filtered by ``dispatched_at``,
because that flag is shared across processes and would make one process's read cause another
to skip rows it hasn't delivered to its own connections yet. ``dispatched_at`` is set here
purely as a "some process has seen this" marker, for monitoring and future pruning.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.events import OutboxEvent
from momentum.realtime.hub import Hub

BATCH = 500


def to_message(row: OutboxEvent) -> dict[str, Any]:
    return {
        "type": "event",
        "id": row.id,
        "event": row.type,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "data": row.payload.get("data", {}),
        "actor": row.payload.get("actor"),
        "request_id": row.payload.get("request_id"),
    }


async def dispatch_pending(session: AsyncSession, hub: Hub, *, after_id: int) -> int:
    """Publish undispatched-to-us rows above ``after_id``, oldest first. Returns the new cursor."""
    rows = (
        (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.id > after_id)
                .order_by(OutboxEvent.id)
                .limit(BATCH)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return after_id
    last_id = after_id
    for row in rows:
        message = to_message(row)
        for channel in row.payload.get("channels") or ():
            hub.publish(channel, message)
        last_id = row.id
    await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id.in_([r.id for r in rows]), OutboxEvent.dispatched_at.is_(None))
        .values(dispatched_at=func.now())
    )
    await session.commit()
    if len(rows) == BATCH:
        # a burst (e.g. a bulk import) left more waiting: keep draining before going back to
        # waiting on the next NOTIFY, or delivery would lag behind by a full LISTEN round trip
        return await dispatch_pending(session, hub, after_id=last_id)
    return last_id
