"""Database sessions for jobs. A job process has no FastAPI runtime to borrow a session factory
from, so it builds one lazily per worker process from ``Settings()`` (the pattern S2.6.1's
``extract_text`` introduced, shared here for the AI jobs)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai.llm import LLM, build_llm
from momentum.ai.usage import DbUsageLog
from momentum.core.db import create_engine, create_session_factory
from momentum.core.settings import Settings

_factories: dict[str, async_sessionmaker[AsyncSession]] = {}
_llms: dict[str, LLM] = {}


def _factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    factory = _factories.get(settings.database_url)
    if factory is None:
        factory = _factories[settings.database_url] = create_session_factory(
            create_engine(settings)
        )
    return factory


@asynccontextmanager
async def job_session() -> AsyncIterator[AsyncSession]:
    """A session whose work is committed when the block exits without an error."""
    async with _factory(Settings())() as session, session.begin():
        yield session


def job_llm() -> LLM:
    """The worker process's gateway (usage logged to ``llm_calls`` like the app's)."""
    settings = Settings()
    llm = _llms.get(settings.database_url)
    if llm is None:
        llm = _llms[settings.database_url] = build_llm(
            settings, DbUsageLog(_factory(settings), settings.ai_monthly_budget_usd)
        )
    return llm
