from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut
from momentum.domain.notifications import service
from momentum.domain.notifications.schemas import (
    NotificationOut,
    NotificationPrefsIn,
    NotificationPrefsOut,
    UnreadCountOut,
)

router = APIRouter(tags=["notifications"])


@router.get(
    "/notifications",
    response_model=ListOut[NotificationOut],
    summary="My notifications (active by default, or archived)",
)
async def list_notifications(
    ctx: CtxDep, uow: UowDep, archived: bool = Query(default=False)
) -> ListOut[NotificationOut]:
    async with uow.transaction() as s:
        await service.sync_due_notifications(s, ctx)
        rows = await service.list_notifications(s, ctx, archived=archived)
        return ListOut(data=[NotificationOut.model_validate(r) for r in rows])


@router.get(
    "/notifications/unread-count", response_model=UnreadCountOut, summary="Unread, unarchived count"
)
async def unread_count(ctx: CtxDep, uow: UowDep) -> UnreadCountOut:
    async with uow.transaction() as s:
        await service.sync_due_notifications(s, ctx)
        return UnreadCountOut(count=await service.unread_count(s, ctx))


@router.post(
    "/notifications/{notification_id}/read", response_model=NotificationOut, summary="Mark read"
)
async def mark_read(notification_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> NotificationOut:
    async with uow.transaction() as s:
        row = await service.set_read(s, ctx, notification_id, True)
        return NotificationOut.model_validate(row)


@router.post(
    "/notifications/{notification_id}/unread", response_model=NotificationOut, summary="Mark unread"
)
async def mark_unread(notification_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> NotificationOut:
    async with uow.transaction() as s:
        row = await service.set_read(s, ctx, notification_id, False)
        return NotificationOut.model_validate(row)


@router.post(
    "/notifications/{notification_id}/archive", response_model=NotificationOut, summary="Archive"
)
async def archive(notification_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> NotificationOut:
    async with uow.transaction() as s:
        row = await service.set_archived(s, ctx, notification_id, True)
        return NotificationOut.model_validate(row)


@router.post(
    "/notifications/{notification_id}/unarchive",
    response_model=NotificationOut,
    summary="Unarchive",
)
async def unarchive(notification_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> NotificationOut:
    async with uow.transaction() as s:
        row = await service.set_archived(s, ctx, notification_id, False)
        return NotificationOut.model_validate(row)


@router.get(
    "/me/prefs/notifications",
    response_model=NotificationPrefsOut,
    summary="My notification preferences (per kind: in_app/email/slack/off) and digest time",
)
async def get_prefs(ctx: CtxDep, uow: UowDep) -> NotificationPrefsOut:
    async with uow.transaction() as s:
        return await service.get_prefs(s, ctx)


@router.put(
    "/me/prefs/notifications",
    response_model=NotificationPrefsOut,
    summary="Set my notification preferences",
)
async def set_prefs(body: NotificationPrefsIn, ctx: CtxDep, uow: UowDep) -> NotificationPrefsOut:
    async with uow.transaction() as s:
        return await service.set_prefs(s, ctx, body)
