"""S4.1.5 AI step actions: the part of a rule that needs a model.

A rule's actions all run inside one savepoint as the rule's author (S4.1.1), so the executor
can't make a gateway call itself — it would hold a write transaction open for seconds. Instead
the ``ai_step`` action writes a ``rule_ai_steps`` row (``domain/rules/engine.py``) and this
module runs it a minute later on the ``ai`` queue (``jobs/ai.py``). The run therefore finishes
before the AI write lands, and counts the step as an action it *queued*; the step carries its
own status (queued → running → done/failed), which is what the run history shows.

Four kinds (the roadmap's sub-kinds):

- ``summarize_to_comment`` — the S3.4.1 thread summary, posted as a comment.
- ``draft_reply`` — a draft reply to the newest comment, posted as a comment.
- ``classify_field`` — one field (``priority`` or a custom field) set from what the task says.
- ``extract_fields`` — every custom field attached to the task's project that is still **empty**,
  filled in from what the task says. A value a person already set is never overwritten.

How the writes behave:

- They run as the rule's author, with ``via="ai"``, so the comment is marked AI (``is_ai``,
  ``created_via="ai"``, the amber accent in the UI) and the activity says the same.
- ``rule_depth`` is the depth the rule's own writes carry, so loop protection (S4.1.1) covers
  what an AI step changes exactly as it covers the other actions.
- **Risk policy** (ai-architecture §4): every kind here is ``low`` risk (a field value, a
  comment), which is what may be applied without a person confirming. A kind above ``low`` is
  refused rather than applied — there is no way for a rule to auto-apply a risky AI write.
- The whole step is one savepoint: a step that fails part-way writes nothing and records why.
- The model never sees ids or picks them: it answers with field names and option labels, which
  are resolved here against the fields the step was actually given.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts, summarize
from momentum.ai.context.builders import task_ctx
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.base import RISK_RANK
from momentum.ai.tools.write_tools import text_doc
from momentum.core.context import Actor, Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.core.settings import Settings
from momentum.core.telemetry import get_logger
from momentum.domain.access import get_visible_task
from momentum.domain.comments.service import create_comment
from momentum.domain.fields.models import FieldDef
from momentum.domain.fields.service import (
    get_task_field_values,
    list_project_fields,
    set_task_field_value,
    validate_value,
)
from momentum.domain.rules.models import Rule, RuleAiStep
from momentum.domain.rules.schemas import AI_STEP_KINDS
from momentum.domain.tasks.service import update_task
from momentum.domain.users.models import User

log = get_logger("rules.ai_step")

BATCH = 10  # steps one job run takes; the job runs every minute
STALE = timedelta(minutes=15)  # a `running` step older than this crashed: one attempt only
MAX_FIELDS = 10  # fields offered to the model in one extract_fields step
PRIORITIES = ("urgent", "high", "medium", "low")
# Every kind writes a field value or a comment: low risk, so a rule may apply it (§4).
KIND_RISK: dict[str, str] = {
    "summarize_to_comment": "low",
    "draft_reply": "low",
    "classify_field": "low",
    "extract_fields": "low",
}
MAX_APPLY_RISK = "low"


@dataclass
class StepResult:
    """What a step wrote, for the run history (and for the evals to score)."""

    summary: str = ""
    values: dict[str, Any] = dc_field(default_factory=dict)  # field name → value written
    comment: str | None = None
    notes: list[str] = dc_field(default_factory=list)
    source: str = ""  # exactly what the model was shown, so an eval judge can check the claims


class FieldGuess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(max_length=100, description="The field's name, exactly as given")
    value: Any = Field(description="The value, in the field's own type")
    reason: str = Field(default="", max_length=200)


class FieldGuesses(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: list[FieldGuess] = Field(
        default_factory=list,
        max_length=MAX_FIELDS,
        description="Only the fields the task itself says something about",
    )


# ---------------- field descriptions and value resolution ----------------


def _field_line(name: str, kind: str, options: list[str]) -> str:
    choices = f", choices: {', '.join(safe(o) for o in options)}" if options else ""
    return f"- {safe(name)} (type: {kind}{choices})"


def _options(field: FieldDef) -> list[str]:
    return [
        str(o["label"])
        for o in (field.options or [])
        if isinstance(o, dict) and not o.get("archived")
    ]


def _option_id(field: FieldDef, label: Any) -> str:
    """A choice field's option label (what the model answers with) → its stored id."""
    want = str(label).strip().lower()
    for o in field.options or []:
        if (
            isinstance(o, dict)
            and not o.get("archived")
            and str(o["label"]).strip().lower() == want
        ):
            return str(o["id"])
    raise ValidationFailed(f"“{label}” isn't one of {field.name}'s choices")


def _custom_value(field: FieldDef, raw: Any) -> Any:
    if field.type == "single_select":
        return validate_value(field, _option_id(field, raw))
    if field.type == "multi_select":
        values = raw if isinstance(raw, list) else [raw]
        return validate_value(field, [_option_id(field, v) for v in values])
    return validate_value(field, raw)


def _priority_value(raw: Any) -> str:
    value = str(raw).strip().lower()
    if value not in PRIORITIES:
        raise ValidationFailed(f"“{raw}” isn't a priority")
    return value


# ---------------- the kinds ----------------


async def _task_block(session: AsyncSession, ctx: Ctx, task_id: uuid.UUID, now: datetime) -> str:
    block = await task_ctx(session, ctx, task_id, now=now)
    return block.text


async def _summarize_to_comment(
    session: AsyncSession, llm: LLM, ctx: Ctx, task_id: uuid.UUID, now: datetime
) -> StepResult:
    summary = await summarize.summarize_thread(session, llm, ctx, task_id, now=now)
    await create_comment(session, ctx, task_id, text_doc(summary.text))
    return StepResult(
        summary=f"Summarized {summary.count} comments",
        comment=summary.text,
        values={},
        # the task and its thread, like the other kinds: what the summary must be true to
        source=await _task_block(session, ctx, task_id, now),
    )


async def _draft_reply(
    session: AsyncSession, llm: LLM, ctx: Ctx, task_id: uuid.UUID, now: datetime
) -> StepResult:
    prompt = prompts.load("ai_step_reply")
    shown = await _task_block(session, ctx, task_id, now)
    out = await llm.complete(
        alias=prompt.alias,
        messages=[
            {"role": "system", "content": prompt.body},
            {"role": "user", "content": shown},
        ],
        feature=prompt.feature,
        prompt_version=prompt.version,
        max_tokens=prompt.max_tokens,
        temperature=prompt.temperature,
        ctx=ctx,
    )
    draft = out.text.strip()
    if not draft:
        raise ValidationFailed("The model wrote an empty reply")
    await create_comment(session, ctx, task_id, text_doc(draft))
    return StepResult(summary="Drafted a reply", comment=draft, source=shown)


async def _guess_fields(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    task_id: uuid.UUID,
    now: datetime,
    lines: list[str],
) -> tuple[FieldGuesses, str]:
    """The guesses, and exactly what the model was shown (which the evals judge against)."""
    prompt = prompts.load("ai_step_fields")
    shown = "\n".join(
        [
            await _task_block(session, ctx, task_id, now),
            '<data source="fields">',
            *lines,
            "</data>",
        ]
    )
    guesses = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=shown,
        schema=FieldGuesses,
        description="Submit the fields you could fill in from the task.",
    )
    return guesses, shown


def _guess_for(guesses: FieldGuesses, name: str) -> FieldGuess | None:
    return next((g for g in guesses.values if g.field.strip().lower() == name.lower()), None)


async def _classify_field(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    task_id: uuid.UUID,
    field_id: str,
    now: datetime,
) -> StepResult:
    if field_id == "priority":
        name, line = "priority", _field_line("priority", "choice", list(PRIORITIES))
        field = None
    else:
        field = await _field_def(session, ctx, uuid.UUID(field_id))
        name, line = field.name, _field_line(field.name, field.type, _options(field))
    guesses, shown = await _guess_fields(session, llm, ctx, task_id, now, [line])
    guess = _guess_for(guesses, name)
    if guess is None or guess.value is None:
        return StepResult(
            summary=f"No value for {name}",
            notes=[f"{name}: not enough in the task"],
            source=shown,
        )
    if field is None:
        value: Any = _priority_value(guess.value)
        await update_task(session, ctx, task_id, {"priority": value})
    else:
        value = _custom_value(field, guess.value)
        await set_task_field_value(session, ctx, task_id, field.id, value)
    return StepResult(
        summary=f"Set {name} to {guess.value}", values={name: guess.value}, source=shown
    )


async def _field_def(session: AsyncSession, ctx: Ctx, field_id: uuid.UUID) -> FieldDef:
    field = await session.get(FieldDef, field_id)
    if field is None or field.workspace_id != ctx.workspace_id or field.deleted_at is not None:
        raise NotFound("Field not found")
    return field


async def _extract_fields(
    session: AsyncSession, llm: LLM, ctx: Ctx, task_id: uuid.UUID, now: datetime
) -> StepResult:
    _task, placement, _role = await get_visible_task(session, ctx, task_id)
    if placement is None:
        raise ValidationFailed("This task isn't in a project, so it has no fields")
    attached = await list_project_fields(session, ctx, placement.project_id)
    filled = {v.field_id for v in await get_task_field_values(session, ctx, task_id)}
    # Only empty fields: a rule must never overwrite what a person put there.
    empty = [f for _pf, f in attached if f.id not in filled][:MAX_FIELDS]
    if not empty:
        return StepResult(
            summary="No empty fields to fill", notes=["every field already has a value"]
        )
    lines = [_field_line(f.name, f.type, _options(f)) for f in empty]
    guesses, shown = await _guess_fields(session, llm, ctx, task_id, now, lines)
    written: dict[str, Any] = {}
    notes: list[str] = []
    for f in empty:
        guess = _guess_for(guesses, f.name)
        if guess is None or guess.value is None:
            continue
        try:
            value = _custom_value(f, guess.value)
        except ValidationFailed as e:
            notes.append(f"{f.name}: {e.detail}")
            continue
        await set_task_field_value(session, ctx, task_id, f.id, value)
        written[f.name] = guess.value
    summary = (
        "Filled in " + ", ".join(written) if written else f"Nothing to fill in ({len(empty)} empty)"
    )
    return StepResult(summary=summary, values=written, notes=notes, source=shown)


async def run_kind(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    task_id: uuid.UUID,
    kind: str,
    field_id: str | None = None,
    *,
    now: datetime | None = None,
) -> StepResult:
    """Do one AI step's work as ``ctx`` (which must already be an AI context). Raises on failure;
    the caller decides what to keep. Used by the queue runner and by the evals."""
    if kind not in AI_STEP_KINDS:
        raise ValidationFailed(f"Unknown AI step {kind}")
    risk = KIND_RISK[kind]
    if RISK_RANK[risk] > RISK_RANK[MAX_APPLY_RISK]:  # pragma: no cover - no such kind yet
        raise ValidationFailed(f"A rule can't apply a {risk}-risk AI step without a person")
    at = now or datetime.now(UTC)
    if kind == "summarize_to_comment":
        return await _summarize_to_comment(session, llm, ctx, task_id, at)
    if kind == "draft_reply":
        return await _draft_reply(session, llm, ctx, task_id, at)
    if kind == "classify_field":
        if not field_id:
            raise ValidationFailed("classify_field needs a field")
        return await _classify_field(session, llm, ctx, task_id, field_id, at)
    return await _extract_fields(session, llm, ctx, task_id, at)


# ---------------- the queue runner ----------------


def step_ctx(user: User, settings: Settings, step: RuleAiStep) -> Ctx:
    """The rule author's context, as AI: the write is marked AI and carries the rule's depth."""
    return Ctx(
        actor=Actor(
            id=user.id,
            workspace_id=user.workspace_id,
            role=user.role,
            is_agent=user.is_agent,
            email=user.email,
            name=user.name,
            timezone=user.timezone,
        ),
        settings=settings,
        via="ai",
        request_id=f"rule-ai-step:{step.rule_id}:{step.id}",
        rule_depth=step.depth,
    )


async def claim_steps(session: AsyncSession, *, limit: int = BATCH) -> tuple[list[uuid.UUID], int]:
    """Mark the oldest queued steps ``running`` and return their ids (the caller commits, so a
    second worker can't pick the same ones up). A step left ``running`` by a crashed worker is
    failed rather than retried: one model call per step, never a silent repeat."""
    now = datetime.now(UTC)
    timed_out = await session.execute(
        update(RuleAiStep)
        .where(RuleAiStep.status == "running", RuleAiStep.started_at < now - STALE)
        .values(status="failed", error="The AI step didn't finish in time", finished_at=now)
        .returning(RuleAiStep.id)
    )
    stale = len(timed_out.all())
    rows = await session.execute(
        select(RuleAiStep.id)
        .where(RuleAiStep.status == "queued")
        .order_by(RuleAiStep.created_at, RuleAiStep.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    ids = [i for (i,) in rows]
    if ids:
        await session.execute(
            update(RuleAiStep)
            .where(RuleAiStep.id.in_(ids))
            .values(status="running", started_at=now)
        )
    return ids, stale


async def run_step(session: AsyncSession, llm: LLM, settings: Settings, step_id: uuid.UUID) -> str:
    """Run one claimed step and record its outcome. Never raises: the row keeps the error, and a
    failed step's partial writes are rolled back with its savepoint."""
    step = await session.get(RuleAiStep, step_id)
    if step is None or step.status != "running":  # someone else took it, or it vanished
        return "skipped"
    kind, task_id, field_id = step.kind, step.task_id, step.field_id
    rule = await session.get(Rule, step.rule_id)
    user = await session.get(User, rule.created_by) if rule is not None else None
    ctx = step_ctx(user, settings, step) if user is not None else None
    savepoint = await session.begin_nested()
    try:
        if ctx is None or user is None or user.status != "active":
            raise ValidationFailed("The person who created this rule is no longer active")
        result = await run_kind(session, llm, ctx, task_id, kind, field_id)
        await savepoint.commit()
        status, summary, error = "done", result.summary[:1000], None
        if result.notes:
            summary = f"{summary} ({'; '.join(result.notes)[:300]})"
    except Exception as e:  # a bad step must never take the worker down
        await savepoint.rollback()
        status, summary, error = "failed", None, (str(e) or type(e).__name__)[:500]
        log.warning("rule_ai_step_failed", step_id=str(step_id), kind=kind, error=error)
    await session.execute(
        update(RuleAiStep)
        .where(RuleAiStep.id == step_id)
        .values(status=status, result=summary, error=error, finished_at=datetime.now(UTC))
    )
    return status
