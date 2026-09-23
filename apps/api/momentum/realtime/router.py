"""``GET /ws`` (upgraded to a websocket): subscribe to task/project/user/team channels and get
live events, with backlog replay on (re)connect. See docs/architecture/realtime-jobs-events.md §3.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any, cast

import structlog
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.runtime import MomentumRuntime
from momentum.core.context import Actor, Ctx
from momentum.core.errors import DomainError
from momentum.core.events import ConsumerOffset, OutboxEvent
from momentum.domain.access import get_visible_project, get_visible_task, get_visible_team
from momentum.realtime.dispatch import to_message
from momentum.realtime.hub import Connection

router = APIRouter()
log = structlog.get_logger("momentum.realtime")

PING_INTERVAL = 25.0
PONG_TIMEOUT = 70.0
REPLAY_LIMIT = 500


async def authorize_channel(session: AsyncSession, ctx: Ctx, channel: str) -> None:
    """Raise a DomainError if the caller may not subscribe to this channel. Reuses the same
    visibility rules as the REST API (momentum.domain.access) — never re-derived here."""
    kind, sep, raw_id = channel.partition(":")
    if not sep:
        raise DomainError("Unknown channel", code="invalid_channel")
    if kind == "user":
        try:
            entity_id = uuid.UUID(raw_id)
        except ValueError:
            raise DomainError("Unknown channel", code="invalid_channel") from None
        if ctx.actor.id != entity_id:
            raise DomainError("Not your channel", code="forbidden")
        return
    try:
        entity_id = uuid.UUID(raw_id)
    except ValueError:
        raise DomainError("Unknown channel", code="invalid_channel") from None
    if kind == "task":
        await get_visible_task(session, ctx, entity_id)
    elif kind == "project":
        await get_visible_project(session, ctx, entity_id)
    elif kind == "team":
        await get_visible_team(session, ctx, entity_id)
    else:
        raise DomainError("Unknown channel", code="invalid_channel")


async def replay(
    session: AsyncSession, ctx: Ctx, channel: str, since: int
) -> list[dict[str, Any]] | None:
    """Backlog for one channel above ``since``, or None when there's too much of it (the
    caller should ask the client to resync — refetch that channel's data — instead)."""
    rows = (
        (
            await session.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.workspace_id == ctx.workspace_id,
                    OutboxEvent.id > since,
                    OutboxEvent.payload["channels"].op("?")(channel),
                )
                .order_by(OutboxEvent.id)
                .limit(REPLAY_LIMIT + 1)
            )
        )
        .scalars()
        .all()
    )
    if len(rows) > REPLAY_LIMIT:
        return None
    return [to_message(row) for row in rows]


async def _build_ctx(rt: MomentumRuntime, websocket: WebSocket) -> Ctx | None:
    from momentum.auth.identity import resolve_user

    # AuthProvider.authenticate only reads headers/cookies (see auth/*.py), which a
    # WebSocket carries the same way a Request does — the type hint is the one HTTP-shaped
    # thing about it.
    principal = await rt.auth.authenticate(cast(Request, websocket))
    if principal is None:
        return None
    async with rt.session_factory() as session, session.begin():
        user, workspace = await resolve_user(session, rt.settings, principal)
    actor = Actor(
        id=user.id,
        workspace_id=workspace.id,
        role=user.role,
        is_agent=user.is_agent,
        email=user.email,
        name=user.name,
        timezone=user.timezone,
    )
    return Ctx(actor=actor, settings=rt.settings)


async def _save_offset(rt: MomentumRuntime, user_id: uuid.UUID, last_event_id: int) -> None:
    async with rt.session_factory() as session, session.begin():
        await session.execute(
            insert(ConsumerOffset)
            .values(consumer=f"ws:{user_id}", last_event_id=last_event_id)
            .on_conflict_do_update(
                index_elements=["consumer"],
                set_={"last_event_id": last_event_id},
                where=ConsumerOffset.last_event_id < last_event_id,
            )
        )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    rt = cast(MomentumRuntime, websocket.app.state.momentum)
    if rt.realtime is None:
        await websocket.close(code=4503, reason="realtime disabled")
        return
    try:
        ctx = await _build_ctx(rt, websocket)
    except Exception:
        log.warning("realtime_auth_error", exc_info=True)
        await websocket.close(code=1011, reason="internal error")
        return
    if ctx is None or ctx.actor.id is None:
        await websocket.close(code=4401, reason="unauthenticated")
        return

    await websocket.accept()
    structlog.contextvars.bind_contextvars(user_id=str(ctx.actor.id))
    conn = Connection(user_id=ctx.actor.id)
    hub = rt.realtime.hub
    await websocket.send_json({"type": "hello", "connection_id": conn.id})

    state = {"last_pong": time.monotonic(), "max_seen": 0}

    async def reader() -> None:
        while True:
            msg = await websocket.receive_json()
            op = msg.get("op")
            if op == "pong":
                state["last_pong"] = time.monotonic()
                continue
            channel = msg.get("channel")
            if not isinstance(channel, str):
                continue
            if op == "unsubscribe":
                hub.unsubscribe(channel, conn)
                continue
            if op != "subscribe":
                continue
            async with rt.session_factory() as session, session.begin():
                try:
                    await authorize_channel(session, ctx, channel)
                except DomainError as e:
                    await websocket.send_json(
                        {"type": "denied", "channel": channel, "reason": e.code}
                    )
                    continue
                since = msg.get("since")
                # since=0 means "everything you have" (a first-ever subscribe on this
                # device): omitting `since` entirely means "just start live" instead.
                backlog: list[dict[str, Any]] | None = []
                if isinstance(since, int) and since >= 0:
                    backlog = await replay(session, ctx, channel, since)
            hub.subscribe(channel, conn)
            if backlog is None:
                await websocket.send_json({"type": "resync", "channel": channel})
            else:
                for event in backlog:
                    await websocket.send_json(event)
                    state["max_seen"] = max(state["max_seen"], cast(int, event["id"]))
            await websocket.send_json({"type": "subscribed", "channel": channel})

    async def writer() -> None:
        while True:
            message = await conn.queue.get()
            await websocket.send_json(message)
            if message.get("type") == "event":
                state["max_seen"] = max(state["max_seen"], cast(int, message["id"]))

    async def pinger() -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            if time.monotonic() - state["last_pong"] > PONG_TIMEOUT:
                raise TimeoutError("no pong from client")
            await websocket.send_json({"type": "ping"})

    tasks = [asyncio.create_task(t()) for t in (reader, writer, pinger)]
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            exc = t.exception()
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, TimeoutError)):
                log.warning("realtime_connection_error", exc_info=exc)
    except Exception:
        log.exception("realtime_connection_crash")
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        hub.drop(conn)
        if state["max_seen"]:
            with contextlib.suppress(Exception):
                await _save_offset(rt, ctx.actor.id, cast(int, state["max_seen"]))
        with contextlib.suppress(Exception):
            await websocket.close()
        log.info("realtime_disconnected", connection_id=conn.id)
