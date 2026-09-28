"""S4.4.2: schedule-based recurrence. `mode: "on_complete"` (the default) spawns the next
instance synchronously when a task is completed (`service.set_completed`); `mode: "on_schedule"`
instead spawns it once the current instance's due date arrives, whether or not it was ever
completed (a standing weekly meeting shouldn't wait on someone to check a box). This is a
maintenance-queue job — not event-driven, since a due date doesn't "happen" the way an edit
does — that finds due, not-yet-succeeded `on_schedule` tasks and calls the same
`spawn_next_occurrence` `set_completed` uses, so the two modes never diverge in behavior."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Actor, Ctx
from momentum.core.settings import Settings
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.service import spawn_next_occurrence
from momentum.domain.users.models import User


def _actor_for(task: Task, user: User | None) -> Actor:
    """Spawning writes a task, which needs someone with real project access — there's no human
    at the keyboard for a schedule-driven spawn, so it acts as the recurring task's own creator
    (same idea as a rule acting as its author). A creator who's lost access since simply means
    the spawn correctly fails with the same permission error a person would get."""
    if user is not None:
        return Actor(
            id=user.id,
            workspace_id=user.workspace_id,
            role=user.role,
            is_agent=user.is_agent,
            email=user.email,
            name=user.name,
            timezone=user.timezone,
        )
    return Actor(id=task.created_by, workspace_id=task.workspace_id)


async def scan_scheduled_recurrences(session: AsyncSession, settings: Settings) -> int:
    """Spawn the next instance of every due `on_schedule` recurring task. Returns the count
    spawned. `spawn_next_occurrence` itself is the idempotency guard (a task that already has
    a `recurrence_parent_id`-linked child is skipped), so re-running this is always safe."""
    today = datetime.now(UTC).date()
    rows = await session.execute(
        select(Task).where(
            Task.recurrence["mode"].astext == "on_schedule",
            Task.due_on <= today,
            Task.deleted_at.is_(None),
        )
    )
    spawned = 0
    for task in rows.scalars():
        if task.created_by is None:
            continue
        placement = (
            await session.execute(
                select(TaskProject).where(TaskProject.task_id == task.id).limit(1)
            )
        ).scalar_one_or_none()
        user = await session.get(User, task.created_by)
        ctx = Ctx(actor=_actor_for(task, user), settings=settings, via="system")
        if await spawn_next_occurrence(session, ctx, task, placement) is not None:
            spawned += 1
    return spawned
