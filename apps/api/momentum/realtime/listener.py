"""Background task (one per app process): LISTEN on Postgres for new outbox rows and hand
them to dispatch_pending. Started from app.py's lifespan, cancelled at shutdown.
"""

from __future__ import annotations

import asyncio

import psycopg
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.core.events import OutboxEvent
from momentum.core.settings import Settings
from momentum.realtime.dispatch import dispatch_pending
from momentum.realtime.hub import Hub

log = structlog.get_logger("momentum.realtime")

# If the LISTEN connection drops (deploy, network blip), retry with backoff instead of spinning.
BACKOFF_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)


async def _starting_cursor(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Start from "now": a fresh process doesn't replay all of history over the live feed
    (per-connection backlog replay, driven by the client's own ``since``, covers that)."""
    async with session_factory() as session:
        value = await session.scalar(select(func.max(OutboxEvent.id)))
        return int(value or 0)


async def run_listener(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], hub: Hub
) -> None:
    """Runs until cancelled. A bad or dropped connection is retried, never left to die quietly."""
    after_id = await _starting_cursor(session_factory)
    attempt = 0
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(
                settings.psycopg_conninfo, autocommit=True
            ) as conn:
                await conn.execute(f"LISTEN {settings.events_channel}")
                log.info("realtime_listening", channel=settings.events_channel)
                attempt = 0
                async with session_factory() as session:
                    after_id = await dispatch_pending(session, hub, after_id=after_id)
                async for _notify in conn.notifies():
                    async with session_factory() as session:
                        after_id = await dispatch_pending(session, hub, after_id=after_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            attempt += 1
            log.warning("realtime_listener_error", retry_in=delay, exc_info=True)
            await asyncio.sleep(delay)
