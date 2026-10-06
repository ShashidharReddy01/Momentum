"""Phase 7.5 (spec §7.6): widget results for 60 s per (widget and its version, viewer, filters),
held by the running app (``MomentumRuntime.dashboard_cache``), never a module global.

The key also carries the newest ``events_outbox`` id, so any change anywhere (every mutation writes
an outbox row in its transaction) makes the next read compute afresh: a cached number is never
older than the last change. It is a small bounded map; the oldest entries go first.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Hashable
from typing import Any

TTL_SECONDS = 60.0
MAX_ENTRIES = 2000


class ResultCache:
    def __init__(self, ttl: float = TTL_SECONDS, max_entries: int = MAX_ENTRIES) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()

    def get(self, key: Hashable) -> Any | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        at, value = hit
        if time.monotonic() - at > self.ttl:
            self._data.pop(key, None)
            return None
        return value

    def put(self, key: Hashable, value: Any) -> None:
        self._data[key] = (time.monotonic(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()
