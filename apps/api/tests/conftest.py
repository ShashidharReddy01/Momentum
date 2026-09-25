"""Test fixtures. Tests need a Postgres with pgvector; set MOMENTUM_TEST_DATABASE_URL
(default: local momentum_test database). Each test session migrates a fresh schema and each
test truncates the Momentum tables afterwards."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from momentum.app import create_app
from momentum.core.db import UnitOfWork, create_engine, create_session_factory
from momentum.core.settings import Settings
from momentum.migrations_runner import upgrade_head

if TYPE_CHECKING:
    from tests.helpers import Clients

TEST_DB = os.environ.get(
    "MOMENTUM_TEST_DATABASE_URL",
    "postgresql+psycopg://momentum:momentum@localhost:5432/momentum_test",
)
TEST_SCHEMA = os.environ.get("MOMENTUM_TEST_SCHEMA", "momentum_test")
KEEP_TABLES = {"alembic_version"}


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "test",
        "database_url": TEST_DB,
        "db_schema": TEST_SCHEMA,
        "worker_mode": "off",
        "realtime_enabled": False,  # most tests don't need a LISTEN connection; realtime
        # tests (tests/test_realtime.py) turn it back on explicitly
        "serve_spa": False,
        "auth_mode": "dev",
        "secret_key": "test-secret",
        "allowed_email_domains": "acme-demo.test",
        "bootstrap_admin_emails": "admin@acme-demo.test",
        "storage_local_dir": tempfile.mkdtemp(prefix="momentum-test-attachments-"),
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def settings() -> Settings:
    return make_settings()


@pytest.fixture(scope="session", autouse=True)
def _migrated(settings: Settings) -> None:
    import sqlalchemy as sa

    eng = sa.create_engine(settings.database_url)
    with eng.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{settings.db_schema}" CASCADE'))
    eng.dispose()
    upgrade_head(settings)


@pytest.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(settings)
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture(autouse=True)
async def _clean(engine: AsyncEngine, settings: Settings) -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        rows = await conn.execute(
            text("select tablename from pg_tables where schemaname = :s"),
            {"s": settings.db_schema},
        )
        tables = [r[0] for r in rows if r[0] not in KEEP_TABLES]
        if tables:
            joined = ", ".join(f'"{settings.db_schema}"."{t}"' for t in tables)
            await conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def uow(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[UnitOfWork]:
    u = UnitOfWork(session_factory())
    yield u
    await u.close()


AppFactory = Callable[..., FastAPI]


@pytest.fixture
def app_factory(settings: Settings) -> AppFactory:
    def _make(**overrides: object) -> FastAPI:
        return create_app(make_settings(**overrides) if overrides else settings)

    return _make


@pytest.fixture
async def client(app_factory: AppFactory) -> AsyncIterator[httpx.AsyncClient]:
    app = app_factory()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-Requested-With": "momentum"},
        ) as c:
            yield c


async def seed_users(uow: UnitOfWork, settings: Settings) -> None:
    from momentum.seed import seed

    async with uow.transaction() as session:
        await seed(session, settings)


@pytest.fixture
async def seeded(uow: UnitOfWork, settings: Settings) -> None:
    await seed_users(uow, settings)


@pytest.fixture
async def as_user(app_factory: AppFactory, seeded: None) -> AsyncIterator[Clients]:
    """``c = await as_user("ravi")`` → an authenticated client for a seeded user."""
    from tests.helpers import Clients

    app = app_factory()
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        yield clients
        await clients.close()
