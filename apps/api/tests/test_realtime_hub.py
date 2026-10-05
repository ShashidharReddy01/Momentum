"""S2.1.1 realtime: the in-process Hub and the outbox -> Hub dispatcher, without any sockets."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.core.db import UnitOfWork
from momentum.core.events import OutboxEvent
from momentum.realtime.dispatch import GAP_WAIT, Cursor, _changes_access, dispatch_pending
from momentum.realtime.hub import Connection, Hub


def test_hub_subscribe_publish_unsubscribe() -> None:
    hub = Hub()
    a, b = Connection(), Connection()
    hub.subscribe("project:1", a)
    hub.subscribe("project:1", b)
    hub.subscribe("task:1", a)

    delivered = hub.publish("project:1", {"type": "event", "id": 1})
    assert delivered == 2
    assert a.queue.get_nowait() == {"type": "event", "id": 1}
    assert b.queue.get_nowait() == {"type": "event", "id": 1}

    hub.unsubscribe("project:1", b)
    assert hub.publish("project:1", {"type": "event", "id": 2}) == 1
    assert a.queue.get_nowait()["id"] == 2
    assert b.queue.empty()

    # a channel nobody's on doesn't error, just delivers to nobody
    assert hub.publish("nobody:home", {"type": "event"}) == 0


def test_hub_drop_removes_every_channel() -> None:
    hub = Hub()
    conn = Connection()
    hub.subscribe("project:1", conn)
    hub.subscribe("task:1", conn)
    hub.drop(conn)
    assert hub.publish("project:1", {}) == 0
    assert hub.publish("task:1", {}) == 0
    assert conn.channels == set()


def test_slow_connection_drops_oldest_instead_of_blocking() -> None:
    conn = Connection()
    conn.queue = type(conn.queue)(maxsize=2)  # small queue to hit the overflow path fast
    conn.send({"type": "event", "id": 1})
    conn.send({"type": "event", "id": 2})
    conn.send({"type": "event", "id": 3})  # queue full: drops id=1, appends an overflow marker
    first = conn.queue.get_nowait()
    second = conn.queue.get_nowait()
    assert first == {"type": "event", "id": 2}
    assert second == {"type": "overflow"}
    assert conn.queue.empty()


async def test_dispatch_pending_publishes_new_rows_and_marks_them(uow: UnitOfWork) -> None:
    ws_id = uuid.uuid4()
    async with uow.transaction() as session:
        r1 = OutboxEvent(
            workspace_id=ws_id,
            type="task.updated",
            entity_type="task",
            entity_id=uuid.uuid4(),
            payload={
                "channels": ["project:p1"],
                "data": {"title": "A"},
                "actor": None,
                "request_id": "r1",
            },
        )
        r2 = OutboxEvent(
            workspace_id=ws_id,
            type="task.assigned",
            entity_type="task",
            entity_id=uuid.uuid4(),
            payload={
                "channels": ["project:p1", "user:u1"],
                "data": {},
                "actor": None,
                "request_id": None,
            },
        )
        session.add_all([r1, r2])
        await session.flush()
        r1_id, r2_id = r1.id, r2.id

    hub = Hub()
    p1, u1 = Connection(), Connection()
    hub.subscribe("project:p1", p1)
    hub.subscribe("user:u1", u1)

    cursor = Cursor(low=r1_id - 1)
    async with uow.transaction() as session:
        await dispatch_pending(session, hub, cursor)
    assert cursor.low >= r2_id

    got_p1 = [p1.queue.get_nowait() for _ in range(2)]
    assert [m["id"] for m in got_p1] == [r1_id, r2_id]
    assert got_p1[0]["data"] == {"title": "A"}
    assert got_p1[1]["request_id"] is None
    got_u1 = u1.queue.get_nowait()
    assert got_u1["id"] == r2_id

    async with uow.transaction() as session:
        # a raw read, bypassing the identity map: `uow`'s session is shared across this test's
        # transaction() blocks (expire_on_commit=False), so session.get() would return the
        # object as it was when first SELECTed by dispatch_pending, before its own UPDATE
        dispatched_at = await session.scalar(
            text("select dispatched_at from events_outbox where id = :id"), {"id": r1_id}
        )
        assert dispatched_at is not None

    # calling again from the same cursor is a no-op: nothing new to publish
    before = cursor.low
    async with uow.transaction() as session:
        await dispatch_pending(session, hub, cursor)
    assert cursor.low == before
    assert p1.queue.empty()


async def test_dispatch_pending_ignores_dispatched_at_as_a_filter(uow: UnitOfWork) -> None:
    """Two "processes" both starting from after_id=0 must both see the same row — dispatched_at
    is a cross-process marker, not a per-reader lock (see dispatch.py's docstring)."""
    ws_id = uuid.uuid4()
    async with uow.transaction() as session:
        row = OutboxEvent(
            workspace_id=ws_id,
            type="task.updated",
            entity_type="task",
            entity_id=uuid.uuid4(),
            payload={"channels": ["project:p1"], "data": {}, "actor": None, "request_id": None},
        )
        session.add(row)
        await session.flush()
        row_id = row.id

    hub_a, hub_b = Hub(), Hub()
    conn_a, conn_b = Connection(), Connection()
    hub_a.subscribe("project:p1", conn_a)
    hub_b.subscribe("project:p1", conn_b)

    async with uow.transaction() as session:
        await dispatch_pending(session, hub_a, Cursor(low=row_id - 1))
    async with uow.transaction() as session:
        await dispatch_pending(session, hub_b, Cursor(low=row_id - 1))

    assert conn_a.queue.get_nowait()["id"] == row_id
    assert conn_b.queue.get_nowait()["id"] == row_id


def _row(type_: str = "task.updated", data: dict[str, object] | None = None) -> OutboxEvent:
    return OutboxEvent(
        workspace_id=uuid.uuid4(),
        type=type_,
        entity_type="task",
        entity_id=uuid.uuid4(),
        payload={"channels": ["project:p9"], "data": data or {}, "actor": None, "request_id": None},
    )


async def test_an_event_that_commits_after_a_later_one_is_still_delivered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Phase 7 (load test): ids are taken at insert, so a slower transaction's lower id becomes
    visible after a higher one. The cursor must not move past it."""
    hub, conn = Hub(), Connection()
    hub.subscribe("project:p9", conn)
    async with session_factory() as slow:
        a = _row()
        slow.add(a)
        await slow.flush()  # id taken, not committed
        async with session_factory() as fast, fast.begin():
            b = _row()
            fast.add(b)
        cursor = Cursor(low=a.id - 1)
        async with session_factory() as s:
            await dispatch_pending(s, hub, cursor, now=0.0)
        assert [conn.queue.get_nowait()["id"]] == [b.id]
        assert cursor.low == a.id - 1  # waiting for a
        await slow.commit()
    async with session_factory() as s:
        await dispatch_pending(s, hub, cursor, now=1.0)
    assert conn.queue.get_nowait()["id"] == a.id  # late, but delivered, and b not again
    assert conn.queue.empty() and cursor.low >= b.id


def test_a_hole_that_never_fills_is_given_up_after_a_while() -> None:
    cursor = Cursor(low=10, seen={12, 13})
    cursor.advance(now=0.0)
    assert cursor.low == 10  # 11 may still commit
    cursor.advance(now=GAP_WAIT - 1)
    assert cursor.low == 10
    cursor.advance(now=GAP_WAIT + 1)  # a rolled-back transaction: move on
    assert cursor.low == 13 and not cursor.seen and not cursor.gaps
    cursor.seen.add(14)
    cursor.advance(now=GAP_WAIT + 2)
    assert cursor.low == 14


def test_only_access_changing_updates_trigger_a_recheck() -> None:
    assert not _changes_access(_row(data={"changes": {"title": ["a", "b"]}}))
    assert _changes_access(_row(data={"changes": {"assignee_id": [None, "u"]}}))
    assert _changes_access(_row(data={"changes": {"parent_id": [None, "t"]}}))
    assert _changes_access(_row("task.assigned"))
    assert _changes_access(_row("project.member_removed"))
    assert not _changes_access(_row("comment.created"))
