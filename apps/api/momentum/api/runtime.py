"""Per-app runtime container stored on ``app.state.momentum`` (no module-level globals)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from momentum.core.settings import Settings

if TYPE_CHECKING:
    from momentum.auth.base import AuthProvider
    from momentum.realtime.hub import Hub


@dataclass
class RealtimeState:
    """Non-None only while the realtime listener is running (see app.py's lifespan)."""

    hub: Hub


@dataclass
class MomentumRuntime:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    auth: AuthProvider
    realtime: RealtimeState | None = None
    extras: dict[str, Any] = field(default_factory=dict)
