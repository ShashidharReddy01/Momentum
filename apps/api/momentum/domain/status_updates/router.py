"""S3.4.3 status updates: list a project's history and post an update."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut
from momentum.core.context import Ctx
from momentum.domain import references
from momentum.domain.status_updates import service
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.status_updates.schemas import (
    StatusCitationOut,
    StatusSections,
    StatusUpdateIn,
    StatusUpdateOut,
)

router = APIRouter(tags=["status updates"])


async def update_out(session: AsyncSession, ctx: Ctx, u: StatusUpdate) -> StatusUpdateOut:
    """With every ``[T-n]``/``[P:…]`` in it resolved for this reader."""
    cites = await references.resolve(session, ctx, u.body_text)
    return StatusUpdateOut(
        id=u.id,
        entity_type=u.entity_type,
        entity_id=u.entity_id,
        status=u.status,
        title=u.title,
        summary=str((u.body or {}).get("summary") or ""),
        sections=StatusSections.model_validate((u.body or {}).get("sections") or {}),
        author_id=u.author_id,
        generated_by_ai=u.generated_by_ai,
        created_at=u.created_at,
        citations=[StatusCitationOut(**c.to_json()) for c in cites],
    )


@router.get(
    "/projects/{project_id}/status-updates",
    response_model=ListOut[StatusUpdateOut],
    summary="A project's status updates, newest first",
)
async def list_status_updates(
    project_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[StatusUpdateOut]:
    async with uow.transaction() as s:
        rows = await service.list_status_updates(s, ctx, project_id)
        return ListOut(data=[await update_out(s, ctx, u) for u in rows])


@router.post(
    "/projects/{project_id}/status-updates",
    response_model=MutationOut[StatusUpdateOut],
    status_code=status.HTTP_201_CREATED,
    summary="Post a status update (sets the project's status; undoable)",
)
async def create_status_update(
    project_id: uuid.UUID, body: StatusUpdateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[StatusUpdateOut]:
    async with uow.transaction() as s:
        m = await service.create_status_update(s, ctx, project_id, body)
        await s.refresh(m.entity)
        return MutationOut(
            data=await update_out(s, ctx, m.entity),
            meta=MutationMeta(activity_id=m.activity_id, batch_id=m.batch_id, version=m.version),
        )
