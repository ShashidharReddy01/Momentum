"""S2.5.1: notification generation and the inbox's reads/writes.

Event-driven kinds (`assigned`, `mentioned`, `commented`, `completed`) are created synchronously,
in the same transaction as the mutation that triggers them (`notify()`, called from
`domain/tasks/service.py` and `domain/comments/service.py`) — not by a separate outbox-consuming
job. This is simpler than a real consumer and gives the same observable result (a notification
exists once the mutation commits), and it sidesteps "no duplicates on dispatcher retry" entirely:
there's no separate dispatch step to retry.

`due_soon`/`overdue` aren't triggered by any single mutation — they're a daily per-user scan.
Rather than add a new timezone-bucketed cron job (this codebase has no precedent for a job that
touches the database at all yet), `sync_due_notifications()` follows the exact pattern
`domain/mytasks` already uses for its own daily rebucketing: computed lazily, once per local
calendar day per user, the next time that user's own data is read (here, `GET /notifications`),
gated by a `notif_sync_date` marker in `users.prefs` so it's a no-op on every other read that day.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import NotFound
from momentum.core.events import emit
from momentum.domain.notifications.models import Notification
from momentum.domain.notifications.schemas import NotificationPrefsIn, NotificationPrefsOut
from momentum.domain.tasks.models import Task
from momentum.domain.users.models import User

COALESCE_WINDOW = timedelta(minutes=10)


def _today_for(tz: str) -> date:
    # Duplicated from `domain.tasks.service.today_for` rather than imported: that module needs to
    # import `notify()` from here, and the reverse import would close a cycle.
    try:
        return datetime.now(ZoneInfo(tz)).date()
    except (KeyError, ValueError):
        return datetime.now(UTC).date()


async def _prefs_for(session: AsyncSession, user_id: uuid.UUID) -> NotificationPrefsOut:
    user = await session.get(User, user_id)
    stored = ((user.prefs or {}).get("notifications") or {}) if user else {}
    return NotificationPrefsOut(
        **{k: v for k, v in stored.items() if k in NotificationPrefsOut.model_fields}
    )


async def get_prefs(session: AsyncSession, ctx: Ctx) -> NotificationPrefsOut:
    if ctx.actor.id is None:
        return NotificationPrefsOut()
    return await _prefs_for(session, ctx.actor.id)


async def set_prefs(
    session: AsyncSession, ctx: Ctx, prefs: NotificationPrefsIn
) -> NotificationPrefsOut:
    await session.execute(
        text(
            "UPDATE users SET prefs = jsonb_set(coalesce(prefs, '{}'::jsonb), '{notifications}', "
            "cast(:value as jsonb)) WHERE id = :uid"
        ),
        {"value": prefs.model_dump_json(), "uid": ctx.actor.id},
    )
    await session.flush()
    return NotificationPrefsOut(**prefs.model_dump())


async def _create_or_coalesce(
    session: AsyncSession,
    ctx: Ctx,
    *,
    user_id: uuid.UUID,
    kind: str,
    entity_type: str,
    entity_id: uuid.UUID,
    title: str,
    snippet: str | None = None,
    activity_id: uuid.UUID | None = None,
) -> None:
    """The actual insert-or-merge, with no actor/prefs guard — `notify()` and
    `sync_due_notifications()` apply those themselves (the latter notifies the actor about their
    own tasks, which is exactly the case `notify()`'s guard exists to block)."""
    cutoff = datetime.now(UTC) - COALESCE_WINDOW
    existing = (
        await session.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.kind == kind,
                Notification.entity_type == entity_type,
                Notification.entity_id == entity_id,
                Notification.archived_at.is_(None),
                Notification.created_at >= cutoff,
            )
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.title = title
        existing.snippet = snippet
        existing.activity_id = activity_id
        existing.read_at = None  # a fresh event re-surfaces a just-read notification as unread
        existing.created_at = datetime.now(UTC)
        notif_id = existing.id
    else:
        row = Notification(
            workspace_id=ctx.workspace_id,
            user_id=user_id,
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            activity_id=activity_id,
            title=title,
            snippet=snippet,
        )
        session.add(row)
        await session.flush()
        notif_id = row.id
    await emit(
        session,
        ctx,
        type="notification.created",
        entity_type="notification",
        entity_id=notif_id,
        data={"kind": kind},
        channels=[f"user:{user_id}"],
    )


async def notify(
    session: AsyncSession,
    ctx: Ctx,
    *,
    user_id: uuid.UUID | None,
    kind: str,
    entity_type: str,
    entity_id: uuid.UUID,
    title: str,
    snippet: str | None = None,
    activity_id: uuid.UUID | None = None,
) -> None:
    """Notify `user_id` about something `ctx.actor` did. Never notifies the actor about their own
    action, and respects the recipient's own per-kind preference."""
    if user_id is None or user_id == ctx.actor.id:
        return
    prefs = await _prefs_for(session, user_id)
    if not getattr(prefs, kind, True):
        return
    await _create_or_coalesce(
        session,
        ctx,
        user_id=user_id,
        kind=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        title=title,
        snippet=snippet,
        activity_id=activity_id,
    )


async def sync_due_notifications(session: AsyncSession, ctx: Ctx) -> None:
    if ctx.actor.id is None:
        return
    user = await session.get(User, ctx.actor.id)
    if user is None:
        return
    today = _today_for(user.timezone)
    if (user.prefs or {}).get("notif_sync_date") == today.isoformat():
        return
    prefs = await _prefs_for(session, ctx.actor.id)
    rows = (
        await session.execute(
            select(Task).where(
                Task.workspace_id == ctx.workspace_id,
                Task.assignee_id == ctx.actor.id,
                Task.completed_at.is_(None),
                Task.deleted_at.is_(None),
                Task.due_on.is_not(None),
            )
        )
    ).scalars()
    for t in rows:
        assert t.due_on is not None
        if t.due_on == today and prefs.due_soon:
            await _create_or_coalesce(
                session,
                ctx,
                user_id=ctx.actor.id,
                kind="due_soon",
                entity_type="task",
                entity_id=t.id,
                title=f'"{t.title}" is due today',
            )
        elif t.due_on < today and prefs.overdue:
            await _create_or_coalesce(
                session,
                ctx,
                user_id=ctx.actor.id,
                kind="overdue",
                entity_type="task",
                entity_id=t.id,
                title=f'"{t.title}" is overdue',
            )
    await session.execute(
        text(
            "UPDATE users SET prefs = jsonb_set(coalesce(prefs, '{}'::jsonb), '{notif_sync_date}', "
            "cast(:value as jsonb)) WHERE id = :uid"
        ),
        {"value": json.dumps(today.isoformat()), "uid": ctx.actor.id},
    )
    await session.flush()


async def list_notifications(
    session: AsyncSession, ctx: Ctx, *, archived: bool = False
) -> list[Notification]:
    rows = await session.execute(
        select(Notification)
        .where(
            Notification.user_id == ctx.actor.id,
            Notification.archived_at.is_not(None)
            if archived
            else Notification.archived_at.is_(None),
        )
        .order_by(Notification.created_at.desc())
        .limit(200)
    )
    return list(rows.scalars())


async def unread_count(session: AsyncSession, ctx: Ctx) -> int:
    rows = await session.execute(
        select(Notification.id).where(
            Notification.user_id == ctx.actor.id,
            Notification.archived_at.is_(None),
            Notification.read_at.is_(None),
        )
    )
    return len(rows.all())


async def _get_own(session: AsyncSession, ctx: Ctx, notification_id: uuid.UUID) -> Notification:
    row = await session.get(Notification, notification_id)
    if row is None or row.user_id != ctx.actor.id:
        raise NotFound("Notification not found")
    return row


async def set_read(
    session: AsyncSession, ctx: Ctx, notification_id: uuid.UUID, read: bool
) -> Notification:
    row = await _get_own(session, ctx, notification_id)
    row.read_at = datetime.now(UTC) if read else None
    await session.flush()
    return row


async def set_archived(
    session: AsyncSession, ctx: Ctx, notification_id: uuid.UUID, archived: bool
) -> Notification:
    row = await _get_own(session, ctx, notification_id)
    row.archived_at = datetime.now(UTC) if archived else None
    await session.flush()
    return row
