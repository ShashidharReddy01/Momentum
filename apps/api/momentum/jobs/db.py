"""Database sessions for jobs. A job process has no FastAPI runtime to borrow a session factory
from, so it builds one lazily per worker process from ``Settings()`` (the pattern S2.6.1's
``extract_text`` introduced, shared here for the AI jobs)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.core.db import create_engine, create_session_factory
from momentum.core.settings import Settings

_factories: dict[str, async_sessionmaker[AsyncSession]] = {}


@asynccontextmanager
async def job_session() -> AsyncIterator[AsyncSession]:
    """A session whose work is committed when the block exits without an error."""
    settings = Settings()
    factory = _factories.get(settings.database_url)
    if factory is None:
        factory = _factories[settings.database_url] = create_session_factory(
            create_engine(settings)
        )
    async with factory() as session, session.begin():
        yield session
