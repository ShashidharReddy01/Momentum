"""POST /undo: reverse a change (or a batch of changes) recorded in the activity log."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from momentum.api.deps import CtxDep, UowDep
from momentum.core.undo import undo

router = APIRouter(tags=["undo"])


class UndoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None


class UndoOut(BaseModel):
    undone: list[uuid.UUID]


@router.post("/undo", response_model=UndoOut, summary="Undo a change or a batch of changes")
async def undo_change(body: UndoIn, ctx: CtxDep, uow: UowDep) -> UndoOut:
    async with uow.transaction() as session:
        rows = await undo(session, ctx, activity_id=body.activity_id, batch_id=body.batch_id)
        return UndoOut(undone=[r.id for r in rows])
