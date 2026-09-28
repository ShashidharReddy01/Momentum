"""S4.3.3 "Template from description" API. Lives in ``momentum.ai`` (not ``domain.templates``)
because it calls the LLM, and domain must not depend on AI (import-linter contract)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from momentum.ai.router import require_llm
from momentum.ai.template_from_brief import TemplateDraft, draft_template, to_payload
from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import MutationOut
from momentum.domain.templates import service
from momentum.domain.templates.schemas import TemplateOut

router = APIRouter(prefix="/ai/templates", tags=["ai-templates"])


class BriefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: str = Field(min_length=1, max_length=1000)


class SaveDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    draft: TemplateDraft


@router.post(
    "/from-brief", response_model=TemplateDraft, summary="Draft a template from a description"
)
async def from_brief(body: BriefIn, ctx: CtxDep, rt: RuntimeDep) -> TemplateDraft:
    llm = require_llm(rt)
    return await draft_template(llm, ctx.with_(via="ai"), body.brief)


@router.post(
    "/from-brief/save",
    response_model=MutationOut[TemplateOut],
    summary="Save a (possibly edited) drafted template",
)
async def save_from_brief(body: SaveDraftIn, ctx: CtxDep, uow: UowDep) -> MutationOut[TemplateOut]:
    payload = to_payload(body.draft)
    async with uow.transaction() as s:
        m = await service.save_template_payload(s, ctx, body.name, body.description, payload)
        return MutationOut.of(m, TemplateOut)
