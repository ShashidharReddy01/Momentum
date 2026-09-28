"""Per-app runtime container stored on ``app.state.momentum`` (no module-level globals)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from momentum.core.settings import Settings

if TYPE_CHECKING:
    from momentum.ai.llm import LLM
    from momentum.ai.tools.registry import ToolRegistry
    from momentum.auth.base import AuthProvider
    from momentum.realtime.hub import Hub


@dataclass
class RealtimeState:
    """Non-None only while the realtime listener is running (see app.py's lifespan)."""

    hub: Hub


def _default_tools() -> ToolRegistry:
    from momentum.ai.tools.catalog import build_registry

    return build_registry()


@dataclass
class MomentumRuntime:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    auth: AuthProvider
    realtime: RealtimeState | None = None
    llm: LLM | None = None  # built in the lifespan (S3.1.1); None only outside a running app
    tools: ToolRegistry = field(default_factory=_default_tools)  # S3.1.2 catalog
    # S5.1.1: host agent-definition directories, added to Momentum's starters (ADR-0009)
    agent_definition_dirs: tuple[Path, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)
