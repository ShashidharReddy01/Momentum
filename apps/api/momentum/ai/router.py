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
    from_brief,
    goal_assist,
    memory,
    nl_rule,
    plan_day,
    portfolio_lines,
    prefs,
    quick_add,
    sse,
    status_draft,
    summarize,
    usage_report,
    workload_rebalance,
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
from momentum.domain.portfolios import service as portfolios
from momentum.domain.status_updates.schemas import StatusUpdateIn
from momentum.domain.status_updates.service import body_text as status_body_text
from momentum.domain.workload import rebalance
from momentum.domain.workspace.service import (
    AiConfig,
    EffectiveAi,
    get_ai_config_for_admin,
    set_ai_config,
)

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


# ---------------- project from a brief (S3.4.6) ----------------


class FromBriefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: str = Field(min_length=1, max_length=from_brief.MAX_BRIEF)
    name: str | None = Field(default=None, max_length=120)
    team_id: uuid.UUID | None = None
    start_on: date | None = None
    end_on: date | None = None


class FromBriefOut(BaseModel):
    action_id: uuid.UUID
    name: str
    team: str
    start_on: date
    end_on: date
    tasks: int
    notes: list[str]
    open_questions: list[str]


@router.post(
    "/projects/from-brief",
    response_model=FromBriefOut,
    summary="Plan a project from a brief (a previewed AI action; creates nothing)",
)
async def ai_project_from_brief(
    body: FromBriefIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> FromBriefOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        r = await from_brief.plan_from_brief(
            s,
            llm,
            ctx,
            rt.tools,
            body.brief,
            now=datetime.now(UTC),
            name=body.name,
            team_id=body.team_id,
            start_on=body.start_on,
            end_on=body.end_on,
        )
        return FromBriefOut(**r.__dict__)


# ---------------- natural language → rule (S4.1.4) ----------------


class RuleCompileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    text: str = Field(min_length=1, max_length=nl_rule.MAX_TEXT)


class RuleDraftOut(BaseModel):
    """Exactly what ``POST /rules`` accepts, so the builder can show it and save it unchanged."""

    name: str
    enabled: bool
    trigger: dict[str, Any]
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    created_from_prompt: str | None


class RuleCompileOut(BaseModel):
    """Either ``rule`` + ``sentence``, or ``question`` when Mo needs to ask rather than guess."""

    rule: RuleDraftOut | None = None
    sentence: str | None = None
    question: str | None = None


@router.post(
    "/rules/compile",
    response_model=RuleCompileOut,
    summary="Turn a sentence into a rule draft for the rule builder (saves nothing)",
)
async def ai_compile_rule(
    body: RuleCompileIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> RuleCompileOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        r = await nl_rule.compile_rule(s, llm, ctx, body.project_id, body.text)
    draft = None
    if r.rule is not None:
        dump = r.rule.model_dump(mode="json", exclude_unset=True)  # only the params that were set
        draft = RuleDraftOut(
            name=r.rule.name,
            enabled=r.rule.enabled,
            trigger=dump["trigger"],
            conditions=dump.get("conditions", []),
            actions=dump["actions"],
            created_from_prompt=r.rule.created_from_prompt,
        )
    return RuleCompileOut(rule=draft, sentence=r.sentence, question=r.question)


# ---------------- AI usage and settings (admin, S3.5.2) ----------------


class ModelAliasesOut(BaseModel):
    fast: str
    default: str
    smart: str
    embed: str


class AdminAiSettingsOut(BaseModel):
    config: AiConfig
    effective: EffectiveAi
    models: ModelAliasesOut


@router.get(
    "/admin/settings",
    response_model=AdminAiSettingsOut,
    summary="Workspace AI settings (admin)",
)
async def get_admin_ai_settings(ctx: CtxDep, uow: UowDep) -> AdminAiSettingsOut:
    async with uow.transaction() as s:
        config, effective = await get_ai_config_for_admin(s, ctx)
    return AdminAiSettingsOut(
        config=config,
        effective=effective,
        models=ModelAliasesOut(
            fast=ctx.settings.llm_model_fast,
            default=ctx.settings.llm_model_default,
            smart=ctx.settings.llm_model_smart,
            embed=ctx.settings.llm_embed_model,
        ),
    )


@router.put(
    "/admin/settings",
    response_model=MutationOut[EffectiveAi],
    summary="Change workspace AI settings (admin)",
)
async def put_admin_ai_settings(
    body: AiConfig, ctx: CtxDep, uow: UowDep
) -> MutationOut[EffectiveAi]:
    async with uow.transaction() as s:
        return MutationOut.of(await set_ai_config(s, ctx, body), EffectiveAi)


@router.get(
    "/admin/usage",
    response_model=usage_report.UsageReport,
    summary="AI usage by feature, user and day (admin)",
)
async def get_admin_ai_usage(
    ctx: CtxDep, uow: UowDep, rt: RuntimeDep, days: int = 30
) -> usage_report.UsageReport:
    async with uow.transaction() as s:
        return await usage_report.get_usage_report(
            s, ctx, days=days, unpriced_models=rt.llm.unpriced_models() if rt.llm else []
        )


# ---------------- portfolio one-liners (S6.2.2) ----------------


class PortfolioLineOut(BaseModel):
    project_id: uuid.UUID
    text: str
    ai: bool  # false: the plain facts line (the model skipped it, or invented a number)


class PortfolioLinesOut(BaseModel):
    lines: list[PortfolioLineOut]


@router.post(
    "/portfolios/{portfolio_id}/lines",
    response_model=PortfolioLinesOut,
    summary="One line per visible project in a portfolio, from its numbers (stores nothing)",
)
async def ai_portfolio_lines(
    portfolio_id: uuid.UUID, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> PortfolioLinesOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        p = await portfolios.get_portfolio(s, ctx, portfolio_id)
        rows, _hidden = await portfolios.portfolio_rows(s, ctx, p)
        facts = [
            portfolio_lines.ProjectFacts(
                id=x.id,
                name=x.name,
                status=x.status,
                total=f["total_tasks"],
                done=f["completed_tasks"],
                overdue=f["overdue_tasks"],
                due_on=x.due_on,
                latest_update=f["latest_update_title"],
            )
            for x, f in rows
        ]
        out = await portfolio_lines.lines_for(llm, ctx, facts, datetime.now(UTC).date())
        return PortfolioLinesOut(
            lines=[PortfolioLineOut(project_id=x.project_id, text=x.text, ai=x.ai) for x in out]
        )


# ---------------- AI for goals (S6.3.2) ----------------


class GoalCheckInDraftBody(BaseModel):
    status: Literal["on_track", "at_risk", "off_track", "on_hold", "complete"]
    title: str
    summary: str


class GoalCheckInDraftOut(BaseModel):
    draft: GoalCheckInDraftBody
    ai: bool  # false: built in code (the model's draft used a number the facts don't have)


class GoalLinkSuggestionOut(BaseModel):
    entity_type: Literal["project"] = "project"
    id: uuid.UUID
    name: str
    reason: str


class GoalLinkSuggestionsOut(BaseModel):
    suggestions: list[GoalLinkSuggestionOut]


@router.post(
    "/goals/{goal_id}/check-in-draft",
    response_model=GoalCheckInDraftOut,
    summary="Draft a goal check-in from its progress, pace and linked work (stores nothing)",
)
async def ai_goal_check_in_draft(
    goal_id: uuid.UUID, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> GoalCheckInDraftOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        r = await goal_assist.draft_check_in(s, llm, ctx, goal_id, datetime.now(UTC).date())
        return GoalCheckInDraftOut(draft=GoalCheckInDraftBody(**r.draft.model_dump()), ai=r.ai)


@router.post(
    "/goals/{goal_id}/suggest-links",
    response_model=GoalLinkSuggestionsOut,
    summary="Projects that look like they support this goal (links nothing)",
)
async def ai_goal_suggest_links(
    goal_id: uuid.UUID, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> GoalLinkSuggestionsOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        found = await goal_assist.suggest_projects(s, llm, ctx, goal_id)
        return GoalLinkSuggestionsOut(
            suggestions=[
                GoalLinkSuggestionOut(id=x.project_id, name=x.name, reason=x.reason) for x in found
            ]
        )


# ---------------- S6.4.2: suggest a workload rebalance ----------------


class RebalanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date | None = Field(default=None, description="A day in the first week (default today)")
    weeks: int = Field(default=6, ge=1, le=26)
    project_id: uuid.UUID | None = Field(default=None, description="Only move this project's work")


class RebalancePersonRef(BaseModel):
    user_id: uuid.UUID
    name: str


class RebalanceShiftOut(BaseModel):
    task_id: uuid.UUID
    key: str
    title: str
    days_later: int


class RebalanceMoveOut(BaseModel):
    kind: Literal["reassign", "start_later", "push"]
    task_id: uuid.UUID
    key: str
    title: str
    project_name: str
    estimate_minutes: int
    week_start: date = Field(description="The overloaded week this move was chosen for")
    from_person: RebalancePersonRef
    to_person: RebalancePersonRef | None
    from_start: date | None
    from_due: date
    to_start: date | None
    to_due: date
    weeks_later: int
    due_moved: bool
    past_project_due: bool
    shifted: list[RebalanceShiftOut]
    text: str
    why: str


class RebalanceWeekOut(BaseModel):
    week_start: date
    capacity_minutes: int
    before_minutes: int
    after_minutes: int


class RebalancePersonOut(BaseModel):
    user_id: uuid.UUID
    name: str
    weeks: list[RebalanceWeekOut]


class RebalanceUnresolvedOut(BaseModel):
    user_id: uuid.UUID
    name: str
    week_start: date
    over_minutes: int
    reason: Literal["nothing_movable", "no_room"]


class RebalanceOut(BaseModel):
    status: Literal["balanced", "partial", "nothing_to_do", "no_estimates"]
    action_id: uuid.UUID | None = Field(description="The proposed action to preview and apply")
    headline: str
    summary: str
    ai: bool = Field(description="The explanation was written by the model (else built in code)")
    moves: list[RebalanceMoveOut]
    people: list[RebalancePersonOut]
    unresolved: list[RebalanceUnresolvedOut]
    limited: bool


def _rebalance_out(sug: workload_rebalance.Suggestion) -> RebalanceOut:
    r = sug.rebalance

    def ref(pid: uuid.UUID) -> RebalancePersonRef:
        return RebalancePersonRef(user_id=pid, name=r.people[pid].name)

    moves = []
    for mv in r.moves:
        it = mv.item
        moves.append(
            RebalanceMoveOut(
                kind=mv.kind,
                task_id=it.id,
                key=it.key,
                title=it.title,
                project_name=it.project_name,
                estimate_minutes=it.minutes,
                week_start=mv.week,
                from_person=ref(mv.person),
                to_person=ref(mv.to_person) if mv.to_person else None,
                from_start=it.start_on,
                from_due=it.due_on,
                to_start=mv.new_start if mv.kind != "reassign" else it.start_on,
                to_due=mv.new_due or it.due_on,
                weeks_later=mv.weeks_later,
                due_moved=mv.due_moved,
                past_project_due=mv.past_project_due,
                shifted=[
                    RebalanceShiftOut(task_id=s.id, key=s.key, title=s.title, days_later=s.days)
                    for s in mv.shifted
                ],
                text=rebalance.describe(r, mv),
                why=rebalance.why(r, mv),
            )
        )
    people = [
        RebalancePersonOut(
            user_id=pid,
            name=p.name,
            weeks=[
                RebalanceWeekOut(
                    week_start=w,
                    capacity_minutes=p.capacity.get(w, 0),
                    before_minutes=round(r.before.get(pid, {}).get(w, 0)),
                    after_minutes=round(r.after.get(pid, {}).get(w, 0)),
                )
                for w in r.weeks
            ],
        )
        for pid, p in r.people.items()
    ]
    return RebalanceOut(
        status=r.status,
        action_id=sug.action_id,
        headline=sug.note.headline,
        summary=sug.note.summary,
        ai=sug.ai,
        moves=moves,
        people=people,
        unresolved=[
            RebalanceUnresolvedOut(
                user_id=u.person,
                name=r.people[u.person].name,
                week_start=u.week,
                over_minutes=u.over,
                reason=u.reason,
            )
            for u in r.unresolved
        ],
        limited=r.limited,
    )


@router.post(
    "/workload/rebalance",
    response_model=RebalanceOut,
    summary="Suggest reassignments and date moves that bring people under capacity (proposes)",
)
async def ai_workload_rebalance(
    body: RebalanceIn, ctx: CtxDep, uow: UowDep, rt: RuntimeDep
) -> RebalanceOut:
    llm = require_llm(rt)
    ctx = ctx.with_(via="ai")
    async with uow.transaction() as s:
        sug = await workload_rebalance.suggest_rebalance(
            s,
            llm,
            ctx,
            rt.tools,
            start=body.start or datetime.now(UTC).date(),
            weeks=body.weeks,
            project_id=body.project_id,
        )
        return _rebalance_out(sug)
