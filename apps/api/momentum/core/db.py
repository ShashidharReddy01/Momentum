"""Database engine, declarative base, common mixins and the unit of work.

All tables live in the configured Postgres schema via the connection ``search_path``,
so Momentum can share a database with a host application (see ADR-0006).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from momentum.core.ids import new_id
from momentum.core.settings import Settings

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={settings.search_path}"},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


class UnitOfWork:
    """Owns one session and the transaction boundary for a request, job or agent step.

    Services wrap their writes in ``async with uow.transaction():``. The outermost block
    commits (or rolls back when ``dry_run`` is set, which is how AI previews are computed);
    nested blocks are transparent, so services compose freely.
    """

    def __init__(self, session: AsyncSession, *, dry_run: bool = False) -> None:
        self.session = session
        self.dry_run = dry_run
        self._depth = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        outermost = self._depth == 0
        self._depth += 1
        try:
            if outermost and not self.session.in_transaction():
                await self.session.begin()
            yield self.session
            if outermost:
                if self.dry_run:
                    await self.session.rollback()
                else:
                    await self.session.commit()
        except BaseException:
            if outermost:
                await self.session.rollback()
            raise
        finally:
            self._depth -= 1

    async def close(self) -> None:
        await self.session.close()
