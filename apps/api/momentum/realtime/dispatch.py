"""Turns new events_outbox rows into Hub publishes.

Each app process tracks its own ``Cursor`` (in memory, seeded from ``max(id)`` at startup by
listener.py) and re-reads every row above it — never filtered by ``dispatched_at``, because that
flag is shared across processes and would make one process's read cause another to skip rows it
hasn't delivered to its own connections yet. ``dispatched_at`` is set here purely as a "some
process has seen this" marker, for monitoring and future pruning.

**Ids commit out of order.** Outbox ids come from a sequence when a row is inserted, not when its
transaction commits, so with concurrent writers id 101 can be visible while 100 is still in
flight. A plain "highest id seen" cursor skipped 100 forever (Phase 7 load test: ~5% of edits
never reached other tabs at 75 concurrent users). The cursor's low-water mark therefore only
moves past an id once it has been delivered, or after ``GAP_WAIT`` seconds (a rolled-back
transaction leaves a hole that never fills); ids above it already delivered are remembered so
re-reads don't publish them twice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.events import OutboxEvent
from momentum.realtime.hub import Hub

BATCH = 500
GAP_WAIT = 30.0  # seconds a missing id may still commit (longer than any normal write)
# events after which someone may no longer be allowed on a channel they're subscribed to:
# every connection re-authorizes its channels straight away (router.py ``guard``)
ACCESS_EVENTS = frozenset(
    {
        "project.updated",  # privacy, team
        "project.archived",
        "project.deleted",
        "project.member_removed",
        "project.member_updated",
        "team.deleted",
        "team.member_removed",
        "team.member_updated",
        "task.deleted",
        "task.removed_from_project",
        "task.follower_removed",
        "task.assigned",  # assignee changes move personal access
        "user.updated",  # S7.5.4: a role change or a disabled account (an admin's action)
    }
)
# a task update re-checks access only when it changes who or what the task belongs to (every
# edit used to make every open connection re-authorize all its channels)
ACCESS_FIELDS = frozenset({"assignee_id", "parent_id"})


@dataclass
class Cursor:
    low: int  # every id at or below this has been delivered (or given up on)
    seen: set[int] = field(default_factory=set)  # delivered ids above ``low``
    gaps: dict[int, float] = field(default_factory=dict)  # missing id -> when first noticed

    def advance(self, now: float) -> None:
        top = max(self.seen, default=self.low)
        while self.low < top:
            nxt = self.low + 1
            if nxt in self.seen:
                self.seen.discard(nxt)
            elif now - self.gaps.setdefault(nxt, now) < GAP_WAIT:
                return  # may still commit: keep re-reading from here
            self.gaps.pop(nxt, None)
            self.low = nxt


def _changes_access(row: OutboxEvent) -> bool:
    if row.type in ACCESS_EVENTS:
        return True
    if row.type != "task.updated":
        return False
    changes = (row.payload.get("data") or {}).get("changes") or {}
    return isinstance(changes, dict) and bool(ACCESS_FIELDS & changes.keys())


def to_message(row: OutboxEvent, channel: str) -> dict[str, Any]:
    """One row can be published to several channels at once (e.g. a subtask event goes to
    both its own `task:<id>` and its parent's); `channel` says which one this particular
    delivery is for, so a connection subscribed to more than one matching channel — and
    so receiving this row more than once — can tell the deliveries apart (or the frontend
    dedupe by `id` and just take the first, since either is the same event)."""
    return {
        "type": "event",
        "id": row.id,
        "event": row.type,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "channel": channel,
        "data": row.payload.get("data", {}),
        "actor": row.payload.get("actor"),
        "request_id": row.payload.get("request_id"),
        # lets the actor's own tab recognize its own echo (it already reconciled the cache
        # from the mutation's own response, which carries the same activity_id) and skip
        # re-invalidating for it — see apps/web/.../lib/realtime/mine.ts
        "activity_id": str(row.activity_id) if row.activity_id else None,
    }


async def dispatch_pending(
    session: AsyncSession, hub: Hub, cursor: Cursor, *, now: float | None = None
) -> None:
    """Publish rows above the cursor this process hasn't delivered yet, oldest first."""
    read_from = cursor.low
    access_changed = False
    delivered: list[int] = []
    while True:
        rows = (
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.id > read_from)
                    .order_by(OutboxEvent.id)
                    .limit(BATCH)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if row.id in cursor.seen:
                continue
            for channel in row.payload.get("channels") or ():
                hub.publish(channel, to_message(row, channel))
            cursor.seen.add(row.id)
            delivered.append(row.id)
            access_changed = access_changed or _changes_access(row)
        if len(rows) < BATCH:
            break
        # a burst (e.g. a bulk import) left more waiting: keep draining before going back to
        # waiting on the next NOTIFY, or delivery would lag behind by a full LISTEN round trip
        read_from = rows[-1].id
    cursor.advance(time.monotonic() if now is None else now)
    if access_changed:
        hub.recheck_all()
    if delivered:
        await session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(delivered), OutboxEvent.dispatched_at.is_(None))
            .values(dispatched_at=func.now())
        )
    await session.commit()
