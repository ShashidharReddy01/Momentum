"""Phase 7.6 S76-03 (spec §5, §5.6, §8.1): a job talking to people.

- ``job.ask``: a question, made once and waited on durably; the answer (or what expiry decided)
  is recorded as the step's output. Every ask declares ``default_on_expiry``.
- ``job.propose``: anything beyond the declared effects goes to the run's person as a proposal
  (preview → confirm → apply → undo), never applied by the job itself.
- Conversation runs (``@Agent …`` on a task that has, or had, one of its jobs): ``job.classify``
  (exact command words first, then one ``fast`` call constrained to the manifest's ``commands``
  plus ``question``), ``job.jobs_on_task``, and two actions a conversation may take **only after a
  confirm ask was answered yes**: ``job.send_instruction`` (to a job of this agent waiting in
  ``job.wait_for_instruction``) and ``job.start_job``.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, create_model
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents.jobs.job import JobState, StepFailed, Suspend, _never
from momentum.agents.packs.pack import PackError
from momentum.core.activity import record_activity
from momentum.core.events import emit
from momentum.core.ids import new_id
from momentum.domain.agents.models import Agent, AgentRun, AgentRunStep
from momentum.domain.asks import service as asks_service
from momentum.domain.asks.models import Ask
from momentum.domain.asks.schemas import AskSpec
from momentum.domain.notifications.service import notify
from momentum.domain.workspace.models import Workspace
from momentum.domain.workspace.service import workspace_timezone

CONVERSE = "converse"


class AskAnswer(BaseModel):
    """What a person (or expiry) decided. ``status``: ``answered`` or ``expired``; an expired
    ask carries its default ``value`` or the ``action`` the pack must take (``route_to_review``)."""

    model_config = ConfigDict(frozen=True)

    ask_id: uuid.UUID
    status: Literal["answered", "expired"]
    value: Any = None
    answered_by: uuid.UUID | None = None
    via: str | None = None
    action: str | None = None

    @property
    def answered(self) -> bool:
        return self.status == "answered"

    @property
    def defaulted(self) -> bool:
        return self.status == "expired"


class Proposed(BaseModel):
    action_id: uuid.UUID
    summary: str


class Intent(BaseModel):
    """A message to the agent: a ``question``, or one of the pack's ``commands``."""

    kind: Literal["command", "question"]
    command: str | None = None
    text: str = ""


class TaskJob(BaseModel):
    run_id: uuid.UUID
    status: str
    capability: str | None
    error: str | None
    waiting_on: str | None
    created_at: datetime
    finished_at: datetime | None
    result: Any = None


def _requester(state: JobState) -> uuid.UUID | None:
    raw = state.trigger.get("requested_by")
    return uuid.UUID(str(raw)) if raw else None


# ---------------------------------------------------------------- asks


async def ask(state: JobState, key: str, spec: dict[str, Any]) -> AskAnswer:
    adapter = TypeAdapter(AskAnswer)
    try:
        parsed = AskSpec.model_validate(spec)
    except ValidationError as e:
        raise PackError(f"Ask {key!r} is malformed: {e}") from e
    if key in state.done:
        answer = cast(AskAnswer, await state.run_step(key, "ask", _never, adapter))
        _note_confirm(state, parsed, answer)
        return answer
    if state.task_id is None:
        raise PackError("A job asks in its task's thread, so it needs a task")
    async with state.txn() as s:
        row = await s.scalar(
            select(Ask).where(
                Ask.run_id == state.run_id, Ask.step_key == key, Ask.status != "superseded"
            )
        )
        if row is None:
            row = await _create(s, state, key, parsed)
        status, ask_id, value = row.status, row.id, row.answer
        answered_by, via, default = row.answered_by, row.answered_via, row.default_on_expiry
        title = row.title
    if status == "open":
        state.claim_key(key)
        raise Suspend({"type": "ask", "ids": [str(ask_id)], "key": key})
    if status == "cancelled":
        raise StepFailed(key, f"The question “{title}” was cancelled")
    if status == "expired" and (default or {}).get("action") == "fail":
        raise StepFailed(key, f"Nobody answered “{title}” in time")
    answer = AskAnswer(
        ask_id=ask_id,
        status="answered" if status == "answered" else "expired",
        value=value,
        answered_by=answered_by,
        via=via,
        action=(default or {}).get("action") if status == "expired" else None,
    )
    await state.record_value(key, "ask", answer.model_dump(mode="json"))
    _note_confirm(state, parsed, answer)
    return answer


def _note_confirm(state: JobState, spec: AskSpec, answer: AskAnswer) -> None:
    if spec.kind == "confirm" and answer.answered and answer.value is True:
        state.confirmed = True


async def _create(s: AsyncSession, state: JobState, key: str, spec: AskSpec) -> Ask:
    agent = await s.get(Agent, state.agent_id)
    run = await s.get(AgentRun, state.run_id)
    workspace = await s.get(Workspace, state.workspace_id)
    assert agent is not None and run is not None and state.task_id is not None
    return await asks_service.create_ask(
        s,
        state.ctx,
        agent=agent,
        run=run,
        step_key=key,
        task_id=state.task_id,
        project_id=state.project_id,
        spec=spec,
        tz=workspace_timezone(workspace) if workspace is not None else "UTC",
    )


# ---------------------------------------------------------------- proposals


async def propose(
    state: JobState, key: str, tool: str, args: dict[str, Any], summary: str | None
) -> Proposed:
    from momentum.ai.actions import ProposedCall
    from momentum.ai.actions import propose as ai_propose

    if state.tools is None:
        raise PackError("Proposals need the tool registry, which this worker didn't provide")
    person = _requester(state)
    if person is None:
        raise PackError("Nobody asked for this job, so there's nobody to propose changes to")
    tools = state.tools

    async def body(s: AsyncSession, _meta: dict[str, Any]) -> Proposed:
        p = await ai_propose(
            s,
            state.ctx,
            tools,
            [ProposedCall(tool, args)],
            source="agent",
            source_id=state.run_id,
            summary=summary,
            proposed_for=person,
        )
        if p.action is None:
            raise ValueError("; ".join(f"{n}: {o.result.summary}" for n, o in p.failures))
        await notify(
            s,
            state.ctx,
            user_id=person,
            kind="agent_proposal",
            entity_type="task" if state.task_id else "agent_run",
            entity_id=state.task_id or state.run_id,
            title=f"{state.agent_name} suggests: {p.action.summary}"[:300],
        )
        return Proposed(action_id=p.action.id, summary=p.action.summary)

    return cast(Proposed, await state.run_step(key, "tool", body, TypeAdapter(Proposed)))


# ---------------------------------------------------------------- conversation


def _words(text: str) -> list[str]:
    text = re.sub(r"@\S+", " ", text)  # "@Bernie rerun …": the mention isn't a word
    return re.findall(r"[a-z0-9_]+", text.casefold())


async def classify(state: JobState, key: str, message: str) -> Intent:
    commands = list(state.pack.manifest.commands)
    words = _words(message)
    if words and words[0] in commands:
        return Intent(kind="command", command=words[0], text=message)
    if not commands:
        return Intent(kind="question", text=message)
    choices = (*commands, "question")
    shape = create_model(
        "IntentChoice",
        intent=(Literal[choices], ...),
    )
    from momentum.agents.jobs.job import JobLLM, document_block

    prompt = (
        "A person wrote this to you about your work on a task. Is it one of your commands"
        f" ({', '.join(commands)}) or a question? Answer with one word from the list.\n\n"
        + document_block("message", message)
    )
    picked = await JobLLM(state).json(key, shape, prompt=prompt, alias="fast", max_tokens=50)
    intent = str(picked.intent)  # type: ignore[attr-defined]
    if intent == "question":
        return Intent(kind="question", text=message)
    return Intent(kind="command", command=intent, text=message)


async def jobs_on_task(state: JobState, key: str) -> list[TaskJob]:
    async def body(s: AsyncSession, _meta: dict[str, Any]) -> list[TaskJob]:
        if state.task_id is None:
            return []
        rows = (
            await s.execute(
                select(AgentRun)
                .where(
                    AgentRun.agent_id == state.agent_id,
                    AgentRun.mode == "job",
                    AgentRun.id != state.run_id,
                    AgentRun.trigger["task_id"].astext == str(state.task_id),
                )
                .order_by(AgentRun.created_at.desc())
                .limit(20)
            )
        ).scalars()
        return [
            TaskJob(
                run_id=r.id,
                status=r.status,
                capability=r.capability,
                error=r.error,
                waiting_on=(r.waiting_on or {}).get("type") if r.status == "waiting" else None,
                created_at=r.created_at,
                finished_at=r.finished_at,
                result=(r.output or {}).get("result"),
            )
            for r in rows
        ]

    return cast(list[TaskJob], await state.run_step(key, "step", body, TypeAdapter(list[TaskJob])))


def _require_confirmed(state: JobState, what: str) -> None:
    if state.capability != CONVERSE:
        raise PackError(f"{what} is for conversation runs")
    if not state.confirmed:
        raise PackError(f"{what} needs a confirm ask answered yes first (spec §5.6)")


async def send_instruction(
    state: JobState, key: str, run_id: uuid.UUID, instruction: dict[str, Any]
) -> None:
    """Deliver an instruction to a job of this agent that waits in ``wait_for_instruction``."""
    _require_confirmed(state, "send_instruction")

    async def body(s: AsyncSession, _meta: dict[str, Any]) -> bool:
        target = await s.get(AgentRun, run_id, with_for_update=True)
        wait = (target.waiting_on or {}) if target is not None else {}
        if (
            target is None
            or target.agent_id != state.agent_id
            or target.status != "waiting"
            or wait.get("type") != "instruction"
        ):
            raise ValueError("That job isn't waiting for an instruction")
        seq = int(
            await s.scalar(
                select(AgentRunStep.seq)
                .where(AgentRunStep.run_id == target.id)
                .order_by(AgentRunStep.seq.desc())
                .limit(1)
            )
            or 0
        )
        now = datetime.now().astimezone()
        s.add(
            AgentRunStep(
                id=new_id(),
                workspace_id=target.workspace_id,
                run_id=target.id,
                seq=seq + 1,
                key=str(wait.get("key")),
                kind="event",
                status="done",
                output={"instruction": instruction, "from_run_id": str(state.run_id)},
                attrs={},
                tokens_in=0,
                tokens_out=0,
                cost_usd=0,
                started_at=now,
                finished_at=now,
            )
        )
        target.status, target.waiting_on = "queued", None
        act = await record_activity(
            s,
            state.ctx,
            entity_type="agent_run",
            entity_id=target.id,
            verb="agent_run.instructed",
            changes={"instruction": (None, instruction)},
        )
        await emit(
            s,
            state.ctx,
            type="agent_run.resumed",
            entity_type="agent_run",
            entity_id=target.id,
            data={"agent_id": str(target.agent_id), "instructed_by": str(state.run_id)},
            channels=[f"run:{target.id}", *state.channels()],
            activity_id=act.id,
        )
        return True

    await state.run_step(key, "effect", body, TypeAdapter(bool))


async def wait_for_instruction(state: JobState, key: str) -> dict[str, Any]:
    if key in state.done:
        out = cast(dict[str, Any], await state.run_step(key, "event", _never, TypeAdapter(dict)))
        return cast(dict[str, Any], out.get("instruction") or {})
    state.claim_key(key)
    raise Suspend({"type": "instruction", "key": key})


async def start_job(
    state: JobState, key: str, input: dict[str, Any], capability: str | None = None
) -> uuid.UUID:
    """Start a new job of this agent on this task (e.g. "rerun with these options")."""
    _require_confirmed(state, "start_job")
    if capability is not None:
        state.pack.capability(capability)

    async def body(s: AsyncSession, _meta: dict[str, Any]) -> uuid.UUID:
        run = AgentRun(
            id=new_id(),
            workspace_id=state.workspace_id,
            agent_id=state.agent_id,
            trigger={
                "type": "converse",
                "task_id": str(state.task_id) if state.task_id else None,
                "project_id": str(state.project_id) if state.project_id else None,
                "requested_by": state.trigger.get("requested_by"),
                "acting_for": state.ctx.acting_for is not None,
                "started_by_run": str(state.run_id),
            },
            dedupe_key=f"converse:{state.run_id}:{key}"[:200],
            status="queued",
            mode="job",
            capability=capability,
            input=input,
            pack_version=state.pack.manifest.version,
            request_id=uuid.uuid4(),
            steps=0,
            trace=[],
            tokens_in=0,
            tokens_out=0,
            cost_usd=0,
        )
        s.add(run)
        await s.flush()
        return run.id

    return cast(uuid.UUID, await state.run_step(key, "effect", body, TypeAdapter(uuid.UUID)))
