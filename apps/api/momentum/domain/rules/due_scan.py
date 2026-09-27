"""S4.1.2: the due-approaching scan. Rules can trigger on ``task.due_approaching``, but nothing
else ever emits that event — a due date doesn't "happen" the way a move or an edit does. This is
a maintenance-queue job (the executor in ``engine.py`` only reacts to outbox events) that looks
for tasks due tomorrow and emits one event each, deduped per (task, due date) so it fires once no
matter how many times the job ticks before the rules executor consumes the event."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Actor, Ctx
from momentum.core.events import OutboxEvent, emit
from momentum.core.settings import Settings
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.service import channels

WINDOW_DAYS = 1  # "approaching" = due tomorrow (UTC; a coarse, workspace-wide scan)


async def _already_emitted(session: AsyncSession, task_id: uuid.UUID, due_on: str) -> bool:
    rows = await session.execute(
        select(OutboxEvent.payload).where(
            OutboxEvent.type == "task.due_approaching", OutboxEvent.entity_id == task_id
        )
    )
    return any((payload.get("data") or {}).get("due_on") == due_on for (payload,) in rows)


async def scan_due_approaching(session: AsyncSession, settings: Settings) -> int:
    """Emit ``task.due_approaching`` for tasks due tomorrow. Returns the number emitted."""
    target = (datetime.now(UTC) + timedelta(days=WINDOW_DAYS)).date()
    due_on = target.isoformat()
    rows = await session.execute(
        select(Task).where(
            Task.due_on == target, Task.completed_at.is_(None), Task.deleted_at.is_(None)
        )
    )
    emitted = 0
    for task in rows.scalars():
        if await _already_emitted(session, task.id, due_on):
            continue
        placements = list(
            (
                await session.execute(select(TaskProject).where(TaskProject.task_id == task.id))
            ).scalars()
        )
        ctx = Ctx(
            actor=Actor(id=None, workspace_id=task.workspace_id), settings=settings, via="system"
        )
        chans = channels(task, placements[0] if placements else None)
        chans += [f"project:{p.project_id}" for p in placements[1:]]
        await emit(
            session,
            ctx,
            type="task.due_approaching",
            entity_type="task",
            entity_id=task.id,
            data={"due_on": due_on},
            channels=chans,
        )
        emitted += 1
    return emitted
