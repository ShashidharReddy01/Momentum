"""In-process pub/sub: one Hub per app process, holding this process's live websocket
connections. Fan-out across processes happens in listener.py via Postgres LISTEN/NOTIFY —
every process independently dispatches the same outbox rows to its own local connections.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)  # identity equality: two connections are never "the same" just by field match
class Connection:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_id: uuid.UUID | None = None
    queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=1000)
    )
    channels: set[str] = field(default_factory=set)

    def send(self, message: dict[str, Any]) -> None:
        if self.queue.full():
            # A stalled reader: drop the oldest queued message rather than block every
            # publisher on it, and tell it once it catches up that it may have missed
            # something so it can resync instead of trusting a silent gap.
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait({"type": "overflow"})
            return
        self.queue.put_nowait(message)


class Hub:
    """Channel name -> the connections currently subscribed to it."""

    def __init__(self) -> None:
        self._channels: dict[str, set[Connection]] = {}

    def subscribe(self, channel: str, conn: Connection) -> None:
        self._channels.setdefault(channel, set()).add(conn)
        conn.channels.add(channel)

    def unsubscribe(self, channel: str, conn: Connection) -> None:
        conns = self._channels.get(channel)
        if conns is not None:
            conns.discard(conn)
            if not conns:
                self._channels.pop(channel, None)
        conn.channels.discard(channel)

    def drop(self, conn: Connection) -> None:
        for channel in list(conn.channels):
            self.unsubscribe(channel, conn)

    def publish(self, channel: str, message: dict[str, Any]) -> int:
        """Fan a message out to every connection on this channel. Returns how many got it."""
        conns = self._channels.get(channel)
        if not conns:
            return 0
        for conn in list(conns):
            conn.send(message)
        return len(conns)
