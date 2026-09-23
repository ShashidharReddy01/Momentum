from __future__ import annotations

import asyncio
import uuid

import psycopg
import pytest
from sqlalchemy import func, select

from momentum.core.activity import Activity, record_activity
from momentum.core.context import Actor, Ctx
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden, NotFound
from momentum.core.events import OutboxEvent, emit
from momentum.core.permissions import Action, can, require
from momentum.core.settings import Settings
from momentum.domain.workspace.service import ensure_default_workspace


def ctx_for(settings: Settings, workspace_id: uuid.UUID, role: str = "member", **kw: object) -> Ctx:
    return Ctx(
        actor=Actor(id=uuid.uuid4(), workspace_id=workspace_id, role=role), settings=settings, **kw
    )  # type: ignore[arg-type]


async def test_dry_run_rolls_back_everything(
    uow: UnitOfWork, settings: Settings, session_factory
) -> None:  # type: ignore[no-untyped-def]
    async with uow.transaction() as session:
        ws = await ensure_default_workspace(session, settings)
    dry = UnitOfWork(session_factory(), dry_run=True)
    async with dry.transaction() as session:
        ctx = ctx_for(settings, ws.id, dry_run=True)
        await record_activity(session, ctx, entity_type="x", entity_id=uuid.uuid4(), verb="x.y")
        assert await emit(session, ctx, type="x.y", entity_type="x", entity_id=uuid.uuid4()) is None
    await dry.close()
    async with uow.transaction() as session:
        assert (await session.execute(select(func.count()).select_from(Activity))).scalar() == 0


async def test_nested_transactions_commit_once(uow: UnitOfWork, settings: Settings) -> None:
    async with uow.transaction() as session:
        ws = await ensure_default_workspace(session, settings)
        async with uow.transaction():
            await record_activity(
                session, ctx_for(settings, ws.id), entity_type="t", entity_id=uuid.uuid4(), verb="v"
            )
    async with uow.transaction() as session:
        assert (await session.execute(select(func.count()).select_from(Activity))).scalar() == 1


async def test_rollback_on_error(uow: UnitOfWork, settings: Settings) -> None:
    with pytest.raises(RuntimeError):
        async with uow.transaction() as session:
            await ensure_default_workspace(session, settings)
            raise RuntimeError("boom")
    async with uow.transaction() as session:
        from momentum.domain.workspace.models import Workspace

        assert (await session.execute(select(func.count()).select_from(Workspace))).scalar() == 0


async def test_outbox_notifies_only_after_commit(uow: UnitOfWork, settings: Settings) -> None:
    conninfo = settings.psycopg_conninfo
    listener = await psycopg.AsyncConnection.connect(conninfo, autocommit=True)
    await listener.execute(f'LISTEN "{settings.events_channel}"')
    gen = listener.notifies(timeout=3)

    async with uow.transaction() as session:
        ws = await ensure_default_workspace(session, settings)
        row = await emit(
            session,
            ctx_for(settings, ws.id),
            type="user.joined",
            entity_type="user",
            entity_id=uuid.uuid4(),
            channels=["user:me"],
        )
        assert row is not None
        outbox_id = row.id
    note = await asyncio.wait_for(anext(aiter(gen)), timeout=3)
    assert note.payload == str(outbox_id)
    await listener.close()
    async with uow.transaction() as session:
        saved = await session.get(OutboxEvent, outbox_id)
        assert saved is not None and saved.payload["channels"] == ["user:me"]


def test_permissions_workspace_rules(settings: Settings) -> None:
    ws = uuid.uuid4()
    member, admin, guest = (ctx_for(settings, ws, r) for r in ("member", "admin", "guest"))
    assert can(admin, Action.WORKSPACE_ADMIN) and not can(member, Action.WORKSPACE_ADMIN)
    assert can(member, Action.PROJECT_CREATE) and not can(guest, Action.PROJECT_CREATE)
    with pytest.raises(Forbidden):
        require(member, Action.USERS_MANAGE)

    class Other:
        workspace_id = uuid.uuid4()

    with pytest.raises(NotFound):
        require(admin, Action.WORKSPACE_VIEW, Other())
