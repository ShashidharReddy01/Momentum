"""Undo registry and executor.

Services record an ``undo_payload`` of the form ``{"op": "<name>", "args": {...}}`` on their
activity rows. Domain modules register a handler per op with :func:`undo_handler`. Undo runs the
handler inside the caller's unit of work and marks the activity (or the whole batch) as undone.
The registry is populated at import time by code (like routers), never by runtime data.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound

UndoHandler = Callable[[AsyncSession, Ctx, dict[str, Any]], Awaitable[None]]

_HANDLERS: dict[str, UndoHandler] = {}
UNDO_WINDOW = timedelta(hours=24)


def undo_handler(op: str) -> Callable[[UndoHandler], UndoHandler]:
    def register(fn: UndoHandler) -> UndoHandler:
        _HANDLERS[op] = fn
        return fn

    return register


def undo_op(op: str, **args: Any) -> dict[str, Any]:
    """Build an undo payload (all values must be JSON-serializable)."""
    return {"op": op, "args": {k: _jsonable(v) for k, v in args.items()}}


def _jsonable(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


class UndoConflict(Conflict):
    code, title = "undo_conflict", "Can't undo"


async def undo(
    session: AsyncSession,
    ctx: Ctx,
    *,
    activity_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
) -> list[Activity]:
    """Undo one activity or a whole batch (newest first). Returns the undone rows."""
    if (activity_id is None) == (batch_id is None):
        raise NotFound("Give exactly one of activity_id or batch_id")
    query = select(Activity).where(Activity.workspace_id == ctx.workspace_id)
    query = (
        query.where(Activity.id == activity_id)
        if activity_id
        else query.where(Activity.batch_id == batch_id)
    )
    rows = list(
        (
            await session.execute(query.order_by(Activity.created_at.desc(), Activity.id.desc()))
        ).scalars()
    )
    if not rows:
        raise NotFound()
    now = datetime.now(UTC)
    for row in rows:
        if row.actor_id != ctx.actor.id and not ctx.actor.is_admin:
            raise Forbidden("Only the person who made a change (or an admin) can undo it")
        if row.undone_at is not None:
            raise UndoConflict("This change was already undone")
        if row.undo_payload is None:
            raise UndoConflict("This change can't be undone")
        if now - row.created_at > UNDO_WINDOW:
            raise UndoConflict("Changes can only be undone within 24 hours")
    for row in rows:
        assert row.undo_payload is not None
        handler = _HANDLERS.get(str(row.undo_payload.get("op")))
        if handler is None:
            raise UndoConflict(f"No undo handler for {row.undo_payload.get('op')}")
        await handler(session, ctx, dict(row.undo_payload.get("args") or {}))
        row.undone_at = now
    await session.flush()
    return rows
