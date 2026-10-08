"""Phase 7.6 S76-02 (spec §4.2-4.5): the durable job engine.

``execute_job`` takes one claimed job (``mode='job'``) and runs its pack's function once more from
the top: finished steps replay from their rows, new steps run and commit one by one, and the pass
ends when the function returns (``succeeded``), raises (``failed``, ``budget_exceeded``, …) or
suspends (``waiting``). It never raises; the run row keeps the outcome.

The rest of this module keeps jobs moving between passes:
- ``create_child`` / ``child_results`` / ``wake_parent``: child jobs (``job.spawn`` / ``gather``);
- ``tick_jobs``: timers that are due, jobs past their maximum age, and passes that died with their
  worker (requeued: replay makes that safe);
- ``wake_on_events``: an outbox consumer that resumes jobs waiting for an event.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents.jobs.job import (
    TERMINAL,
    ChildRef,
    ChildResult,
    Interrupted,
    Job,
    JobState,
    OutOfTime,
    StepFailed,
    Suspend,
    Txn,
    _Done,
)
from momentum.agents.packs.pack import PackError
from momentum.agents.runtime import (
    ANSWERING,
    FAILURES_BEFORE_ALERT,
    _check_access,
    _NoAccess,
    _person,
    _tell_requester,
    _usage,
    alert_admins,
)
from momentum.agents.triggers import agent_ctx, on_behalf_ctx
from momentum.ai.errors import AIDisabled, BudgetExceeded
from momentum.ai.llm import LLM
from momentum.core.context import Actor, Ctx
from momentum.core.errors import DomainError
from momentum.core.events import ConsumerOffset, OutboxEvent, emit
from momentum.core.ids import new_id
from momentum.core.settings import Settings
from momentum.core.storage import build_storage
from momentum.core.telemetry import get_logger
from momentum.domain.agents.models import Agent, AgentRun, AgentRunStep
from momentum.domain.agents.runs import recent_statuses
from momentum.domain.tasks import service as tasks_service
from momentum.domain.users.models import User

log = get_logger("agents.jobs")
EVENTS_CONSUMER = "agent_jobs"
STALE_MARGIN = timedelta(minutes=2)
MAX_CRASHES = 3  # a pass that keeps dying with its worker fails instead of looping


@dataclass
class _Outcome:
    status: str
    error: str | None = None
    output: dict[str, Any] | None = None
    waiting_on: dict[str, Any] | None = None
    resume_at: datetime | None = None


class _Stop(Exception):
    def __init__(self, outcome: _Outcome) -> None:
        super().__init__(outcome.status)
        self.outcome = outcome


def system_ctx(workspace_id: uuid.UUID, settings: Settings) -> Ctx:
    return Ctx(actor=Actor(id=None, workspace_id=workspace_id), settings=settings, via="system")


def _run_channels(run: AgentRun) -> list[str]:
    t = run.trigger or {}
    out = [f"run:{run.id}", f"workspace:{run.workspace_id}"]
    if run.parent_run_id is not None:
        out.append(f"run:{run.parent_run_id}")
    if t.get("task_id"):
        out.append(f"task:{t['task_id']}")
    if t.get("requested_by"):
        out.append(f"user:{t['requested_by']}")
    return out


# ---------------------------------------------------------------- one pass


async def execute_job(
    txn: Txn,
    llm: LLM,
    settings: Settings,
    packs: Any,
    run_id: uuid.UUID,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Run one claimed job for one pass and record what happened; returns the run's status.
    ``packs`` is the app's ``PackRegistry``. ``txn`` opens a committed-on-exit transaction (the
    worker's ``job_session``; ``uow.transaction`` in tests): each step gets its own."""
    state: JobState | None = None
    outcome: _Outcome | None = None
    async with txn() as s:
        run = await s.get(AgentRun, run_id)
        if run is None or run.status != "running" or run.mode != "job":
            return "skipped"
        try:
            state, handler = await _prepare(s, llm, settings, packs, run, txn, sleep)
        except _Stop as stop:
            outcome = stop.outcome
        else:
            outcome = None
    if outcome is None and state is not None:
        outcome = await _run(state, handler)
    assert outcome is not None
    return await _finish(txn, settings, run_id, outcome, state)


async def _prepare(
    s: AsyncSession,
    llm: LLM,
    settings: Settings,
    packs: Any,
    run: AgentRun,
    txn: Txn,
    sleep: Callable[[float], Awaitable[None]],
) -> tuple[JobState, Callable[[Job], Awaitable[Any]]]:
    agent = await s.get(Agent, run.agent_id)
    account = await s.get(User, agent.user_id) if agent is not None else None
    if agent is None or account is None:
        raise _Stop(_Outcome("failed", "The agent no longer exists"))
    if not settings.agents_enabled or not agent.enabled:
        raise _Stop(
            _Outcome("paused", f"{agent.name} is turned off", waiting_on={"type": "agent_off"})
        )
    if not settings.packs_enabled:
        raise _Stop(_Outcome("paused", "Packs are turned off", waiting_on={"type": "packs_off"}))
    pack = packs.packs.get(agent.pack_key) if agent.kind == "pack" and packs is not None else None
    if pack is None:
        raise _Stop(_Outcome("failed", f"{agent.name}'s pack isn't loaded on this server"))
    handler = pack.capabilities.get(run.capability) if run.capability else pack.run
    if handler is None:
        what = f"capability {run.capability!r}" if run.capability else "a job function"
        raise _Stop(_Outcome("failed", f"{pack.key} has no {what}"))
    trigger = dict(run.trigger or {})
    requester = await _person(s, trigger.get("requested_by"))
    for_user = await _person(s, trigger.get("for_user_id"))
    if trigger.get("for_user_id") and for_user is None:
        raise _Stop(_Outcome("cancelled", "The person this job was for is no longer active"))
    ctx = (
        on_behalf_ctx(for_user, settings)
        if for_user is not None
        else agent_ctx(agent, account, settings)
    )
    consented = trigger.get("type") in ANSWERING or bool(trigger.get("acting_for"))
    if for_user is None and requester is not None and consented:
        # spec §8.1: the person who asked consents to the declared effects, within what both
        # of them can see
        ctx = ctx.with_(
            acting_for=Actor(
                id=requester.id,
                workspace_id=requester.workspace_id,
                role=requester.role,
                email=requester.email,
                name=requester.name,
                timezone=requester.timezone,
            )
        )
    ctx = ctx.with_(request_id=str(run.request_id))
    try:
        await _check_access(s, agent, ctx, trigger)
    except _NoAccess as e:
        raise _Stop(_Outcome("failed", str(e))) from e
    rows = list(
        (
            await s.execute(
                select(AgentRunStep).where(AgentRunStep.run_id == run.id).order_by(AgentRunStep.seq)
            )
        ).scalars()
    )
    done = {r.key: _Done(r.kind, r.output, r.output_ref) for r in rows if r.status == "done"}
    root = run.id
    parent = run.parent_run_id
    while parent is not None:
        root = parent
        parent = await s.scalar(select(AgentRun.parent_run_id).where(AgentRun.id == parent))
    task_id = trigger.get("task_id")
    project_id = trigger.get("project_id")
    state = JobState(
        txn=txn,
        llm=llm,
        settings=settings,
        storage=build_storage(settings),
        run_id=run.id,
        root_run_id=root,
        workspace_id=run.workspace_id,
        agent_id=agent.id,
        agent_user_id=account.id,
        agent_name=agent.name,
        pack=pack,
        ctx=ctx,
        trigger=trigger,
        input=dict(run.input or {}),
        capability=run.capability,
        task_id=uuid.UUID(str(task_id)) if task_id else None,
        project_id=uuid.UUID(str(project_id)) if project_id else None,
        active_before=run.active_seconds,
        done=done,
        next_seq=max((r.seq for r in rows), default=0) + 1,
        sleep=sleep,
    )
    return state, handler


async def _run(state: JobState, handler: Callable[[Job], Awaitable[Any]]) -> _Outcome:
    try:
        result = await handler(Job(state))
    except Suspend as e:
        return _Outcome("waiting", waiting_on=e.waiting_on, resume_at=e.resume_at)
    except Interrupted as e:
        return _Outcome("interrupted", str(e))
    except StepFailed as e:
        return _Outcome("failed", f"Failed at {e.key}: {e.message}"[:2000])
    except BudgetExceeded as e:
        return _Outcome("budget_exceeded", e.detail)
    except AIDisabled as e:
        return _Outcome("cancelled", e.detail)
    except OutOfTime as e:
        return _Outcome("failed", str(e))
    except PackError as e:
        return _Outcome("failed", f"Pack error: {e}"[:2000])
    except DomainError as e:
        return _Outcome("failed", e.detail)
    except Exception as e:  # a pack bug between steps: the job fails, the worker keeps going
        log.exception("agent_job_failed", run_id=str(state.run_id), pack=state.pack.key)
        return _Outcome("failed", f"Something went wrong ({type(e).__name__})")
    return _Outcome(
        "succeeded", output={"result": TypeAdapter(Any).dump_python(result, mode="json")}
    )


async def _finish(
    txn: Txn, settings: Settings, run_id: uuid.UUID, outcome: _Outcome, state: JobState | None
) -> str:
    async with txn() as s:
        run = await s.get(AgentRun, run_id, with_for_update=True)
        assert run is not None
        agent = await s.get(Agent, run.agent_id)
        account = await s.get(User, agent.user_id) if agent is not None else None
        ctx = (
            agent_ctx(agent, account, settings)
            if agent is not None and account is not None
            else system_ctx(run.workspace_id, settings)
        ).with_(request_id=str(run.request_id))
        if state is not None:
            run.active_seconds = state.active_seconds()
            if state.logs:
                run.trace = [*(run.trace or []), *state.logs]
        run.tokens_in, run.tokens_out, run.cost_usd = await _usage(s, run.id)
        run.steps = int(
            await s.scalar(
                select(func.count()).select_from(AgentRunStep).where(AgentRunStep.run_id == run.id)
            )
            or 0
        )
        if run.status != "running" or outcome.status == "interrupted":
            # cancelled or paused by a person while this pass ran: their decision stands
            return run.status
        if outcome.status == "waiting":
            assert outcome.waiting_on is not None
            if await _condition_met(s, outcome.waiting_on):
                run.status, run.waiting_on, run.resume_at = "queued", None, None
            else:
                run.status, run.waiting_on, run.resume_at = (
                    "waiting",
                    outcome.waiting_on,
                    outcome.resume_at,
                )
                await emit(
                    s,
                    ctx,
                    type="agent_run.waiting",
                    entity_type="agent_run",
                    entity_id=run.id,
                    data={"waiting_on": outcome.waiting_on.get("type")},
                    channels=_run_channels(run),
                )
            return run.status
        if outcome.status == "paused":
            run.status, run.error, run.waiting_on = "paused", outcome.error, outcome.waiting_on
            return run.status
        run.status, run.error = outcome.status, outcome.error
        run.output = outcome.output
        run.waiting_on, run.resume_at = None, None
        run.finished_at = datetime.now(UTC)
        await s.flush()
        await _after_terminal(s, settings, ctx, run, agent)
        return run.status


async def _after_terminal(
    s: AsyncSession, settings: Settings, ctx: Ctx, run: AgentRun, agent: Agent | None
) -> None:
    """A job ended: wake its parent, tell the person who asked when it didn't work out, alert the
    admins on a budget stop or repeated failures, and announce it."""
    if run.parent_run_id is not None:
        await wake_parent(s, settings, run.parent_run_id)
    if agent is not None and run.parent_run_id is None:
        await _tell_requester(s, ctx, agent, run, run.status, run.error)
        if run.status == "budget_exceeded":
            await alert_admins(
                s, ctx, agent, f"{agent.name} stopped: budget used up", run.error or ""
            )
        if run.status == "failed":
            recent = await recent_statuses(s, agent.id, FAILURES_BEFORE_ALERT)
            if len(recent) == FAILURES_BEFORE_ALERT and all(x == "failed" for x in recent):
                await alert_admins(
                    s,
                    ctx,
                    agent,
                    f"{agent.name} failed {FAILURES_BEFORE_ALERT} times in a row",
                    run.error or "",
                )
    await emit(
        s,
        ctx,
        type="agent_run.finished",
        entity_type="agent_run",
        entity_id=run.id,
        data={
            "agent_id": str(run.agent_id),
            "status": run.status,
            "task_id": (run.trigger or {}).get("task_id"),
            "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        },
        channels=_run_channels(run),
    )


async def _condition_met(s: AsyncSession, waiting_on: dict[str, Any]) -> bool:
    """Whether a job about to wait already has what it waits for (a child that finished while
    this pass ran, a timer already due): then it's queued again instead."""
    kind = waiting_on.get("type")
    if kind == "children":
        ids = [uuid.UUID(x) for x in waiting_on.get("ids") or []]
        results = await child_results(s, ids)
        finished = sum(1 for r in results if r.status in TERMINAL)
        return finished == len(results) if waiting_on.get("mode") != "any" else finished > 0
    if kind == "timer":
        return datetime.fromisoformat(str(waiting_on["until"])) <= datetime.now(UTC)
    return False


# ---------------------------------------------------------------- children


async def create_child(
    s: AsyncSession,
    state: JobState,
    capability: str,
    input: dict[str, Any],
    *,
    title: str,
    key: str,
    task: Literal["subtask", "same"] | None,
) -> ChildRef:
    """Inside the parent's ``spawn`` step: the child's subtask (by default) and its queued run."""
    limits = state.limits
    count = int(
        await s.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.parent_run_id == state.run_id)
        )
        or 0
    )
    if count >= limits.max_children:
        raise PackError(
            f"{state.pack.key} can start at most {limits.max_children} child jobs per job"
        )
    child_task: uuid.UUID | None = None
    if task == "subtask" and state.task_id is not None:
        if not state.pack.manifest.declares("tasks.create_subtask"):
            raise PackError(
                f"{state.pack.key} may not tasks.create_subtask (spawn with task=None instead)"
            )
        sub = await tasks_service.create_subtask(s, state.ctx, state.task_id, title[:500])
        await tasks_service.update_task(
            s, state.ctx, sub.entity.id, {"assignee_id": state.agent_user_id}
        )
        child_task = sub.entity.id
    elif task == "same":
        child_task = state.task_id
    t = state.trigger
    child = AgentRun(
        id=new_id(),
        workspace_id=state.workspace_id,
        agent_id=state.agent_id,
        trigger={
            "type": "spawn",
            "task_id": str(child_task) if child_task else None,
            "project_id": str(state.project_id) if state.project_id else None,
            "requested_by": t.get("requested_by"),
            "for_user_id": t.get("for_user_id"),
            "acting_for": state.ctx.acting_for is not None,
            "parent_run_id": str(state.run_id),
            "key": key,
            "title": title[:200],
            "concurrency": limits.concurrency,
        },
        dedupe_key=f"spawn:{state.run_id}:{key}"[:200],
        status="queued",
        mode="job",
        parent_run_id=state.run_id,
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
    s.add(child)
    await s.flush()
    return ChildRef(run_id=child.id, key=key, task_id=child_task)


async def child_results(s: AsyncSession, ids: list[uuid.UUID]) -> list[ChildResult]:
    rows = (await s.execute(select(AgentRun).where(AgentRun.id.in_(ids)))).scalars()
    out: list[ChildResult] = []
    for r in rows:
        t = r.trigger or {}
        out.append(
            ChildResult(
                run_id=r.id,
                key=str(t.get("key") or ""),
                task_id=uuid.UUID(str(t["task_id"])) if t.get("task_id") else None,
                status=r.status,
                output=(r.output or {}).get("result"),
                error=r.error,
            )
        )
    return out


async def wake_parent(s: AsyncSession, settings: Settings, parent_id: uuid.UUID) -> None:
    """A child ended: queue its parent when what it gathers is complete. Both sides lock the
    parent row, so a child finishing while the parent is about to wait is never missed."""
    parent = await s.get(AgentRun, parent_id, with_for_update=True)
    if parent is None or parent.status != "waiting" or not parent.waiting_on:
        return
    if parent.waiting_on.get("type") != "children" or not await _condition_met(
        s, parent.waiting_on
    ):
        return
    parent.status, parent.waiting_on, parent.resume_at = "queued", None, None
    await _emit_resumed(s, settings, parent)


async def _emit_resumed(s: AsyncSession, settings: Settings, run: AgentRun) -> None:
    await emit(
        s,
        system_ctx(run.workspace_id, settings),
        type="agent_run.resumed",
        entity_type="agent_run",
        entity_id=run.id,
        data={"agent_id": str(run.agent_id)},
        channels=_run_channels(run),
    )


# ---------------------------------------------------------------- between passes


@dataclass
class TickStats:
    woken: int = 0
    expired: int = 0
    requeued: int = 0
    failed: int = 0
    ids: list[uuid.UUID] = field(default_factory=list)


async def tick_jobs(s: AsyncSession, settings: Settings, now: datetime | None = None) -> TickStats:
    """Once a minute, before claiming: wake jobs whose timer is due, expire jobs older than
    ``MOMENTUM_AGENT_JOB_MAX_AGE_DAYS``, and requeue a pass that died with its worker (safe:
    finished steps replay, the step that was running rolled back with its transaction)."""
    now = now or datetime.now(UTC)
    stats = TickStats()
    due = (
        await s.execute(
            select(AgentRun)
            .where(
                AgentRun.mode == "job",
                AgentRun.status == "waiting",
                AgentRun.resume_at.is_not(None),
                AgentRun.resume_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    for run in due:
        wait = run.waiting_on or {}
        if wait.get("type") == "timer" and wait.get("key"):
            # the timer is met: record it, so the next pass replays past it whatever its clock
            await _record_wait(s, run, str(wait["key"]), "sleep", wait.get("until"))
        run.status, run.waiting_on, run.resume_at = "queued", None, None
        await _emit_resumed(s, settings, run)
        stats.woken += 1
    old = (
        await s.execute(
            select(AgentRun)
            .where(
                AgentRun.mode == "job",
                AgentRun.status.in_(("queued", "waiting", "paused")),
                AgentRun.created_at < now - timedelta(days=settings.agent_job_max_age_days),
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    for run in old:
        run.status = "expired"
        run.error = f"The job was open longer than {settings.agent_job_max_age_days} days"
        run.finished_at, run.waiting_on, run.resume_at = now, None, None
        agent = await s.get(Agent, run.agent_id)
        await s.flush()
        await _after_terminal(s, settings, system_ctx(run.workspace_id, settings), run, agent)
        stats.expired += 1
    stale_after = (
        timedelta(seconds=settings.agent_job_max_active_s + settings.agent_step_timeout_s)
        + STALE_MARGIN
    )
    stale = (
        await s.execute(
            select(AgentRun)
            .where(
                AgentRun.mode == "job",
                AgentRun.status == "running",
                AgentRun.started_at < now - stale_after,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    for run in stale:
        if run.attempt >= MAX_CRASHES:
            run.status, run.finished_at = "failed", now
            run.error = "The job kept stopping before it finished"
            agent = await s.get(Agent, run.agent_id)
            await s.flush()
            await _after_terminal(s, settings, system_ctx(run.workspace_id, settings), run, agent)
            stats.failed += 1
        else:
            run.status, run.attempt = "queued", run.attempt + 1
            stats.requeued += 1
        stats.ids.append(run.id)
    await s.flush()
    return stats


async def _record_wait(s: AsyncSession, run: AgentRun, key: str, kind: str, output: Any) -> None:
    """Record a met wait (a due timer, an event) as the waiting step's output."""
    seq = int(
        await s.scalar(
            select(func.coalesce(func.max(AgentRunStep.seq), 0)).where(
                AgentRunStep.run_id == run.id
            )
        )
        or 0
    )
    now = datetime.now(UTC)
    s.add(
        AgentRunStep(
            id=new_id(),
            workspace_id=run.workspace_id,
            run_id=run.id,
            seq=seq + 1,
            key=key,
            kind=kind,
            status="done",
            output=output,
            attrs={},
            tokens_in=0,
            tokens_out=0,
            cost_usd=0,
            started_at=now,
            finished_at=now,
        )
    )
    await s.flush()


async def wake_on_events(s: AsyncSession, settings: Settings, *, batch: int = 500) -> int:
    """Resume jobs waiting for an event (``job.wait_for_event``): the event is recorded as the
    waiting step's output and the job is queued (a paused job keeps its pause and gets the event
    when it resumes). The caller commits."""
    cursor = (
        await s.execute(
            select(ConsumerOffset)
            .where(ConsumerOffset.consumer == EVENTS_CONSUMER)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if cursor is None:
        newest = (await s.execute(select(func.max(OutboxEvent.id)))).scalar_one()
        s.add(ConsumerOffset(consumer=EVENTS_CONSUMER, last_event_id=newest or 0))
        await s.flush()
        return 0
    waiting = list(
        (
            await s.execute(
                select(AgentRun).where(
                    AgentRun.mode == "job",
                    AgentRun.status.in_(("waiting", "paused")),
                    AgentRun.waiting_on.is_not(None),
                )
            )
        ).scalars()
    )
    watchers = [r for r in waiting if (r.waiting_on or {}).get("type") == "event"] + [
        r for r in waiting if ((r.waiting_on or {}).get("was") or {}).get("type") == "event"
    ]
    events = list(
        (
            await s.execute(
                select(OutboxEvent)
                .where(OutboxEvent.id > cursor.last_event_id)
                .order_by(OutboxEvent.id)
                .limit(batch)
            )
        ).scalars()
    )
    woken = 0
    for ev in events:
        cursor.last_event_id = ev.id
        for run in list(watchers):
            wait = run.waiting_on or {}
            wait = wait if wait.get("type") == "event" else wait.get("was") or {}
            if run.workspace_id != ev.workspace_id or wait.get("event") != ev.type:
                continue
            data = (ev.payload or {}).get("data") or {}
            if wait.get("task_id") and wait["task_id"] not in (
                str(ev.entity_id),
                str(data.get("task_id") or ""),
            ):
                continue
            await _record_wait(
                s,
                run,
                str(wait.get("key")),
                "event",
                {
                    "event_id": ev.id,
                    "type": ev.type,
                    "entity_type": ev.entity_type,
                    "entity_id": str(ev.entity_id),
                    "data": data,
                },
            )
            if run.status == "waiting":
                run.status, run.waiting_on = "queued", None
                await _emit_resumed(s, settings, run)
            else:
                run.waiting_on = {**(run.waiting_on or {}), "was": None}
            watchers.remove(run)
            woken += 1
    await s.flush()
    return woken
