"""AI endpoints. S3.1.3: read and decide on proposed AI actions (api-conventions: problem+json
errors, ``{data}`` envelopes)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from momentum.ai import actions
from momentum.ai.models import AiAction
from momentum.api.deps import CtxDep, RuntimeDep, UowDep

router = APIRouter(prefix="/ai", tags=["ai"])


class DiffRowOut(BaseModel):
    entity_type: str
    entity_id: str
    label: str
    verb: str
    changes: dict[str, list[Any]]
    display: dict[str, list[Any]]


class AiOperationOut(BaseModel):
    tool: str
    args: dict[str, Any]
    summary: str
    risk: Literal["low", "medium", "high"]
    diff: list[DiffRowOut]


class AiActionOut(BaseModel):
    id: uuid.UUID
    source: str
    summary: str
    risk: Literal["low", "medium", "high"]
    state: Literal["proposed", "approved", "applied", "rejected", "expired", "undone", "failed"]
    operations: list[AiOperationOut]
    applied_batch_id: uuid.UUID | None
    error: str | None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None


class AiActionEnvelope(BaseModel):
    data: AiActionOut


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_high_risk: bool = False


class ApplyOut(BaseModel):
    data: AiActionOut
    outcome: Literal["applied", "repreviewed", "failed"]


def action_out(a: AiAction) -> AiActionOut:
    return AiActionOut(
        id=a.id,
        source=a.source,
        summary=a.summary,
        risk=a.risk,
        state=a.state,
        operations=[
            AiOperationOut(
                tool=op["tool"],
                args=op.get("args") or {},
                summary=op.get("summary") or "",
                risk=op.get("risk") or "low",
                diff=[DiffRowOut(**d) for d in op.get("diff") or []],
            )
            for op in a.operations
        ],
        applied_batch_id=a.applied_batch_id,
        error=a.error,
        created_at=a.created_at,
        expires_at=a.expires_at,
        decided_at=a.decided_at,
    )


@router.get("/actions/{action_id}", response_model=AiActionEnvelope, summary="A proposed AI action")
async def get_ai_action(action_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> AiActionEnvelope:
    async with uow.transaction() as s:
        return AiActionEnvelope(data=action_out(await actions.get_action(s, ctx, action_id)))


@router.post(
    "/actions/{action_id}/apply",
    response_model=ApplyOut,
    summary="Apply a proposed AI action (re-previews instead if its targets changed)",
)
async def apply_ai_action(
    action_id: uuid.UUID, body: ApplyIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> ApplyOut:
    async with uow.transaction() as s:
        r = await actions.apply_action(
            s, ctx, rt.tools, action_id, confirmed=body.confirm_high_risk
        )
        return ApplyOut(data=action_out(r.action), outcome=r.outcome)


@router.post("/actions/{action_id}/reject", response_model=AiActionEnvelope, summary="Dismiss")
async def reject_ai_action(action_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> AiActionEnvelope:
    async with uow.transaction() as s:
        return AiActionEnvelope(data=action_out(await actions.reject_action(s, ctx, action_id)))


@router.post(
    "/actions/{action_id}/undo", response_model=AiActionEnvelope, summary="Undo an applied action"
)
async def undo_ai_action(action_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> AiActionEnvelope:
    async with uow.transaction() as s:
        return AiActionEnvelope(data=action_out(await actions.undo_action(s, ctx, action_id)))
