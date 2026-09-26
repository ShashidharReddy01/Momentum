"""AI endpoints. S3.1.3: read and decide on proposed AI actions (api-conventions: problem+json
errors, ``{data}`` envelopes)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import (
    actions,
    breakdown,
    chat,
    citations,
    memory,
    plan_day,
    prefs,
    quick_add,
    sse,
    status_draft,
    summarize,
    write,
)
from momentum.ai.command import run_command
from momentum.ai.context import Screen
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.loop import Emit
from momentum.ai.models import AiAction
from momentum.ai.prefs import AiPrefs
from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut, MutationOut
from momentum.core.errors import ValidationFailed
from momentum.domain.status_updates.schemas import StatusUpdateIn
from momentum.domain.status_updates.service import body_text as status_body_text

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


# ---------------- Ask Mo chat (S3.3.1) ----------------


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    screen: ScreenIn | None = None


@router.post(
    "/chat",
    summary="Ask Mo (SSE: conversation, tool_call, tool_result, token, citation, "
    "action_proposed, action_applied, clarify, done, error)",
    response_class=StreamingResponse,
)
async def ai_chat(body: ChatIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep) -> StreamingResponse:
    llm = require_llm(rt)
    screen = (body.screen or ScreenIn()).to_screen()
    ctx = ctx.with_(via="ai")
    # the question is stored (and committed) before Mo starts, so it survives a failed answer
    async with uow.transaction() as s:
        turn = await chat.start_turn(
            s, ctx, body.text, conversation_id=body.conversation_id, screen=screen
        )
        ids = (turn.conversation.id, turn.message.id)

    async def work(session: AsyncSession, emit: Emit) -> None:
        await chat.run_chat(
            session, llm, ctx, rt.tools, ids, screen=screen, now=datetime.now(UTC), emit=emit
        )

    return sse.stream(rt, work)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    context_type: Literal["global", "task", "project"]
    context_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CitationOut(BaseModel):
    ref: str
    type: Literal["task", "project"]
    valid: bool
    id: str | None = None
    key: str | None = None
    title: str | None = None


class ChatStepOut(BaseModel):
    name: str
    ok: bool | None = None
    summary: str | None = None
    preview: bool | None = None


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    text: str
    steps: list[ChatStepOut] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    action_id: uuid.UUID | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    grounded: bool | None = None
    rating: Literal[-1, 1] | None = None
    created_at: datetime


class ConversationDetailOut(BaseModel):
    data: ConversationOut
    messages: list[ChatMessageOut]


@router.get(
    "/conversations", response_model=ListOut[ConversationOut], summary="My Ask Mo conversations"
)
async def list_ai_conversations(ctx: CtxDep, uow: UowDep) -> ListOut[ConversationOut]:
    async with uow.transaction() as s:
        rows = await chat.list_conversations(s, ctx)
        return ListOut(data=[ConversationOut.model_validate(c) for c in rows])


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailOut,
    summary="One of my conversations, with its messages (citations checked for me now)",
)
async def get_ai_conversation(
    conversation_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ConversationDetailOut:
    async with uow.transaction() as s:
        v = await chat.get_conversation(s, ctx, conversation_id)
        messages = []
        for m in v.messages:
            c = m.content or {}
            messages.append(
                ChatMessageOut(
                    id=m.id,
                    role=m.role,
                    text=str(c.get("text") or ""),
                    steps=[ChatStepOut(**st) for st in c.get("steps") or []],
                    citations=[CitationOut(**ci) for ci in c.get("citations") or []],
                    action_id=c.get("action_id"),
                    candidates=c.get("candidates") or [],
                    grounded=c.get("grounded"),
                    rating=v.ratings.get(m.id),
                    created_at=m.created_at,
                )
            )
        return ConversationDetailOut(
            data=ConversationOut.model_validate(v.conversation), messages=messages
        )


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: Literal["ai_message", "ai_action"]
    target_id: uuid.UUID
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    target_type: str
    target_id: uuid.UUID
    rating: int
    comment: str | None


@router.put("/feedback", response_model=FeedbackOut, summary="Rate an answer or action 👍/👎")
async def put_ai_feedback(body: FeedbackIn, ctx: CtxDep, uow: UowDep) -> FeedbackOut:
    async with uow.transaction() as s:
        fb = await chat.set_feedback(
            s,
            ctx,
            target_type=body.target_type,
            target_id=body.target_id,
            rating=body.rating,
            comment=body.comment,
        )
        return FeedbackOut.model_validate(fb)


# ---------------- summaries (S3.4.1) ----------------


class SummarizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["task_thread", "inbox"]
    task_id: uuid.UUID | None = None


class SummaryCitationOut(BaseModel):
    ref: str
    type: Literal["task", "project", "comment"]
    valid: bool
    id: str | None = None
    key: str | None = None
    title: str | None = None
    created_at: str | None = None


class SummaryOut(BaseModel):
    summary: str
    citations: list[SummaryCitationOut]
    cached: bool
    count: int
    omitted: int
    created_at: datetime | None


@router.post(
    "/summarize",
    response_model=SummaryOut,
    summary="Summarize a task's comment thread, or my unread inbox (cached by content)",
)
async def ai_summarize(body: SummarizeIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep) -> SummaryOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        if body.target == "task_thread":
            if body.task_id is None:
                raise ValidationFailed("task_id is required to summarize a thread")
            r = await summarize.summarize_thread(s, llm, ctx, body.task_id, now=datetime.now(UTC))
        else:
            r = await summarize.summarize_inbox(s, llm, ctx, now=datetime.now(UTC))
        return SummaryOut(
            summary=r.text,
            citations=[SummaryCitationOut(**c) for c in r.citations],
            cached=r.cached,
            count=r.count,
            omitted=r.omitted,
            created_at=r.created_at,
        )


# ---------------- break into subtasks (S3.4.2) ----------------


class BreakdownIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hint: str | None = Field(default=None, max_length=500)


class BreakdownOut(BaseModel):
    action_id: uuid.UUID
    notes: list[str]
    count: int


@router.post(
    "/tasks/{task_id}/subtasks",
    response_model=BreakdownOut,
    summary="Propose subtasks for a task (a previewed AI action; creates nothing)",
)
async def ai_breakdown(
    task_id: uuid.UUID, body: BreakdownIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> BreakdownOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        r = await breakdown.break_down(
            s, llm, ctx, rt.tools, task_id, hint=body.hint, now=datetime.now(UTC)
        )
        assert r.action_id is not None
        return BreakdownOut(action_id=r.action_id, notes=r.notes, count=r.count)


# ---------------- draft status update (S3.4.3) ----------------


class StatusDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=7, ge=1, le=31, description="How far back to look")


class StatusDraftOut(BaseModel):
    draft: StatusUpdateIn
    notes: list[str]
    facts: dict[str, int]
    since: date
    citations: list[CitationOut]


@router.post(
    "/projects/{project_id}/status-draft",
    response_model=StatusDraftOut,
    summary="Draft a status update from the project's recent activity (stores nothing)",
)
async def ai_status_draft(
    project_id: uuid.UUID, body: StatusDraftIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> StatusDraftOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        r = await status_draft.draft_status(
            s, llm, ctx, project_id, now=datetime.now(UTC), days=body.days
        )
        text = status_body_text(r.draft)
        cites = await citations.resolve(s, ctx, text)
        return StatusDraftOut(
            draft=r.draft,
            notes=r.notes,
            facts=r.facts,
            since=r.since,
            citations=[CitationOut(**c.to_json()) for c in cites],
        )


# ---------------- writing help (S3.4.4) ----------------


class WriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: write.Action
    text: str = Field(min_length=1, max_length=write.MAX_CHARS)
    tone: write.Tone | None = None
    language: str | None = Field(
        default=None, min_length=2, max_length=40, pattern=r"^[A-Za-zÀ-ÿ ()\-]+$"
    )


class WriteOut(BaseModel):
    text: str


@router.post(
    "/write", response_model=WriteOut, summary="Rewrite text (a suggestion; nothing is stored)"
)
async def ai_write(body: WriteIn, ctx: CtxDep, rt: RuntimeDep) -> WriteOut:
    llm = require_llm(rt)
    if body.action == "translate" and not body.language:
        raise ValidationFailed("Choose a language to translate into")
    if not body.text.strip():
        raise ValidationFailed("Select some text first")
    text = await write.rewrite(
        llm,
        ctx.with_(via="ai"),
        action=body.action,
        text=body.text,
        tone=body.tone,
        language=body.language,
    )
    return WriteOut(text=text)


# ---------------- plan my day (S3.4.5) ----------------


class PlanDayOut(BaseModel):
    action_id: uuid.UUID | None = Field(description="null when the day already matches the plan")
    rationale: str
    today: list[str]
    later: list[str]
    notes: list[str]
    citations: list[CitationOut]


@router.post(
    "/plan-my-day",
    response_model=PlanDayOut,
    summary="Propose today's order for my tasks (a previewed change to My Tasks)",
)
async def ai_plan_my_day(ctx: CtxDep, uow: UowDep, rt: RuntimeDep) -> PlanDayOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        r = await plan_day.plan_day(s, llm, ctx, rt.tools, now=datetime.now(UTC))
        cites = await citations.resolve(s, ctx, r.rationale)
        return PlanDayOut(
            action_id=r.action_id,
            rationale=r.rationale,
            today=r.today,
            later=r.later,
            notes=r.notes,
            citations=[CitationOut(**c.to_json()) for c in cites],
        )
