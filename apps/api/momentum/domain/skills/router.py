"""Phase 7.6 S76-05 (spec §7.2): agents' skills: reading (members), authoring and deciding
(workspace admins and the pack's stewards)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut
from momentum.domain.skills import service
from momentum.domain.skills.service import SkillOut, skill_out

router = APIRouter(tags=["skills"])


class SkillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack_key: str = Field(min_length=1, max_length=60)
    scope_type: Literal["workspace", "entity", "project"] = "workspace"
    scope_id: uuid.UUID | None = None
    kind: Literal["hint", "rule", "example", "field_map"]
    field: str | None = Field(default=None, max_length=200)
    content: dict[str, Any]
    note: str | None = Field(default=None, max_length=1000)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)
    content: dict[str, Any] | None = Field(
        default=None, description="Approve only: the edited content (a new version)"
    )


@router.get("/skills", response_model=ListOut[SkillOut], summary="Agents' skills")
async def list_skills(
    ctx: CtxDep,
    uow: UowDep,
    pack_key: str | None = Query(default=None, max_length=60),
    status: str | None = Query(default=None, max_length=12),
    scope_type: str | None = Query(default=None, max_length=12),
    scope_id: uuid.UUID | None = None,
) -> ListOut[SkillOut]:
    async with uow.transaction() as s:
        rows = await service.list_skills(
            s, ctx, pack_key=pack_key, status=status, scope_type=scope_type, scope_id=scope_id
        )
        return ListOut(data=[skill_out(x) for x in rows])


@router.get("/skills/{skill_id}", response_model=SkillOut, summary="One skill")
async def get_skill(skill_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> SkillOut:
    async with uow.transaction() as s:
        return skill_out(await service.get_skill(s, ctx, skill_id))


@router.post(
    "/skills",
    response_model=SkillOut,
    status_code=201,
    summary="Write a skill (admins, stewards): active at once; personal values are refused",
)
async def author_skill(body: SkillIn, ctx: CtxDep, uow: UowDep) -> SkillOut:
    async with uow.transaction() as s:
        return skill_out(
            await service.author(
                s,
                ctx,
                pack_key=body.pack_key,
                scope_type=body.scope_type,
                scope_id=body.scope_id,
                kind=body.kind,
                content=body.content,
                field=body.field,
                note=body.note,
            )
        )


async def _decide(
    skill_id: uuid.UUID, decision: service.Decision, body: DecisionIn, ctx: Any, uow: Any
) -> SkillOut:
    async with uow.transaction() as s:
        return skill_out(
            await service.decide(s, ctx, skill_id, decision, note=body.note, content=body.content)
        )


@router.post(
    "/skills/{skill_id}/approve",
    response_model=SkillOut,
    summary="Approve a proposed skill, optionally edited (a new version)",
)
async def approve(skill_id: uuid.UUID, body: DecisionIn, ctx: CtxDep, uow: UowDep) -> SkillOut:
    return await _decide(skill_id, "approve", body, ctx, uow)


@router.post("/skills/{skill_id}/reject", response_model=SkillOut, summary="Reject a proposal")
async def reject(skill_id: uuid.UUID, body: DecisionIn, ctx: CtxDep, uow: UowDep) -> SkillOut:
    return await _decide(skill_id, "reject", body, ctx, uow)


@router.post("/skills/{skill_id}/retire", response_model=SkillOut, summary="Retire a skill")
async def retire(skill_id: uuid.UUID, body: DecisionIn, ctx: CtxDep, uow: UowDep) -> SkillOut:
    return await _decide(skill_id, "retire", body, ctx, uow)
