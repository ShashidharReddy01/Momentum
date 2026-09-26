"""AI endpoints. S3.1.3: read and decide on proposed AI actions (api-conventions: problem+json
errors, ``{data}`` envelopes)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import actions, memory, prefs, quick_add, sse
from momentum.ai.command import run_command
from momentum.ai.context import Screen
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.loop import Emit
from momentum.ai.models import AiAction
from momentum.ai.prefs import AiPrefs
from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut, MutationOut

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


# ---------------- workspace memory (S3.1.5) ----------------


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    scope: Literal["workspace", "team", "project"]
    scope_id: uuid.UUID | None
    text: str
    created_at: datetime
    updated_at: datetime


class MemoryCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["workspace", "team", "project"] = "workspace"
    scope_id: uuid.UUID | None = None
    text: str = Field(min_length=1, max_length=memory.MAX_TEXT)


class MemoryPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=memory.MAX_TEXT)


@router.get("/memory", response_model=ListOut[MemoryOut], summary="Memory bullets of a scope")
async def list_ai_memory(
    ctx: CtxDep,
    uow: UowDep,
    scope: Literal["workspace", "team", "project"] = "workspace",
    scope_id: uuid.UUID | None = None,
) -> ListOut[MemoryOut]:
    async with uow.transaction() as s:
        rows = await memory.list_memory(s, ctx, scope, scope_id)
        return ListOut(data=[MemoryOut.model_validate(m) for m in rows])


@router.post(
    "/memory",
    response_model=MutationOut[MemoryOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add a memory bullet",
)
async def create_ai_memory(
    body: MemoryCreateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[MemoryOut]:
    async with uow.transaction() as s:
        m = await memory.create_memory(s, ctx, body.scope, body.scope_id, body.text)
        return MutationOut.of(m, MemoryOut)


@router.patch("/memory/{memory_id}", response_model=MutationOut[MemoryOut], summary="Edit a bullet")
async def update_ai_memory(
    memory_id: uuid.UUID, body: MemoryPatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[MemoryOut]:
    async with uow.transaction() as s:
        return MutationOut.of(await memory.update_memory(s, ctx, memory_id, body.text), MemoryOut)


@router.delete(
    "/memory/{memory_id}", response_model=MutationOut[MemoryOut], summary="Remove a bullet"
)
async def delete_ai_memory(
    memory_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[MemoryOut]:
    async with uow.transaction() as s:
        return MutationOut.of(await memory.delete_memory(s, ctx, memory_id), MemoryOut)


# ---------------- smart quick-add (S3.2.1) ----------------


class QuickAddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)


@router.post(
    "/quick-add",
    response_model=quick_add.QuickAddParseOut,
    summary="Read task fields from free text (the AI half of quick add; creates nothing)",
)
async def parse_quick_add(
    body: QuickAddIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> quick_add.QuickAddParseOut:
    llm = require_llm(rt)
    async with uow.transaction() as s:
        return await quick_add.parse(s, llm, ctx, body.text, now=datetime.now(UTC))


def require_llm(rt: Any) -> LLM:
    if rt.llm is None:
        raise AIUnavailable(reason="not_configured")
    return rt.llm  # type: ignore[no-any-return]


# ---------------- ⌘K natural-language commands (S3.2.2) ----------------


class ScreenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["home", "my_tasks", "inbox", "project", "task", "search", "other"] = "other"
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    view: str | None = Field(default=None, max_length=20)
    selected_task_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)

    def to_screen(self) -> Screen:
        return Screen(
            kind=self.kind,
            project_id=self.project_id,
            task_id=self.task_id,
            view=self.view,
            selected_task_ids=list(self.selected_task_ids),
        )


class CommandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)
    screen: ScreenIn | None = None


@router.post(
    "/command",
    summary="Run a natural-language command (SSE: tool_call, tool_result, token, "
    "action_proposed, action_applied, clarify, done, error)",
    response_class=StreamingResponse,
)
async def ai_command(body: CommandIn, ctx: CtxDep, rt: RuntimeDep) -> StreamingResponse:
    llm = require_llm(rt)
    screen = (body.screen or ScreenIn()).to_screen()
    ctx = ctx.with_(via="ai")

    async def work(session: AsyncSession, emit: Emit) -> None:
        await run_command(
            session, llm, ctx, rt.tools, body.text, screen=screen, now=datetime.now(UTC), emit=emit
        )

    return sse.stream(rt, work)


@router.get("/prefs", response_model=AiPrefs, summary="My AI preferences")
async def get_ai_prefs(ctx: CtxDep, uow: UowDep) -> AiPrefs:
    async with uow.transaction() as s:
        return await prefs.get_prefs(s, ctx)


@router.put("/prefs", response_model=AiPrefs, summary="Set my AI preferences")
async def put_ai_prefs(body: AiPrefs, ctx: CtxDep, uow: UowDep) -> AiPrefs:
    async with uow.transaction() as s:
        return await prefs.set_prefs(s, ctx, body)
