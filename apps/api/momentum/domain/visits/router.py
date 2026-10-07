"""Phase 7.5 (spec §9.1): the visit beacon."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from momentum.api.deps import CtxDep, UowDep
from momentum.domain.visits import service
from momentum.domain.visits.service import Scope

router = APIRouter(prefix="/visits", tags=["visits"])


class VisitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope
    scope_id: uuid.UUID | None = None


class VisitOut(BaseModel):
    last_seen_at: datetime


@router.put(
    "",
    response_model=VisitOut,
    summary="I looked at Home, a project or a portfolio (at most one write per 5 minutes)",
)
async def put_visit(body: VisitIn, ctx: CtxDep, uow: UowDep) -> VisitOut:
    async with uow.transaction() as s:
        return VisitOut(last_seen_at=await service.record_visit(s, ctx, body.scope, body.scope_id))
