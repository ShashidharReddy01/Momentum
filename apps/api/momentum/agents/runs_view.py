"""S5.1.3: reading agent runs (the runs page and an agent's run history).

Who sees a run, and how much of it:
- **full** — workspace admins, and the person the run was for (``requested_by`` / ``for_user_id``).
  A run a person asked for only ever saw what both could see (``ctx.acting_for``), so its trace
  holds nothing they couldn't reach.
- **summary** — anyone else who can see the run's task or project. A scheduled or event run
  works with the agent's own access, so its tool results and answer may mention things this
  viewer can't see: the step list keeps what happened (tool, ok, when) but not the text.
- nobody else: the run doesn't exist for them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.models import AiAction
from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound
from momentum.core.ids import task_key
from momentum.domain.access import get_visible_project, get_visible_task
from momentum.domain.agents.models import RUN_STATUSES, Agent, AgentRun, AgentRunStep
from momentum.domain.users.models import User

Detail = Literal["full", "summary"]
HISTORY_LIMIT = 50


class RunTaskOut(BaseModel):
    id: uuid.UUID
    key: str
    title: str


class RunProjectOut(BaseModel):
    id: uuid.UUID
    name: str


class RunPersonOut(BaseModel):
    id: uuid.UUID
    name: str


class RunAgentOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    avatar: str


class RunActionOut(BaseModel):
    id: uuid.UUID
    summary: str
    state: str
    risk: str
    proposed_for: RunPersonOut | None
    # the viewer can decide it (only the person it was proposed for can)
    mine: bool


class RunStepOut(BaseModel):
    at: str
    kind: str
    summary: str
    name: str | None = None
    ok: bool | None = None


class RunProgressOut(BaseModel):
    done: int
    total: int
    label: str | None = None


class AgentRunOut(BaseModel):
    id: uuid.UUID
    agent: RunAgentOut
    status: str
    # Phase 7.6 S76-02: durable jobs (mode "job"); one-shot runs leave these empty
    mode: str = "oneshot"
    capability: str | None = None
    parent_run_id: uuid.UUID | None = None
    waiting_on: str | None = None  # what a waiting job waits for: ask · children · timer · event
    progress: RunProgressOut | None = None
    attempt: int = 0
    active_seconds: int = 0
    trigger: str
    task: RunTaskOut | None
    project: RunProjectOut | None
    requested_by: RunPersonOut | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    error: str | None
    proposals: int
    applied: int


class JobStepOut(BaseModel):
    seq: int
    key: str
    kind: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    error: str | None
    output: Any = None  # full viewers only; a classified pack's only to those who see the task


class AgentRunDetailOut(AgentRunOut):
    detail: Detail
    trace: list[RunStepOut]
    answer: str | None
    comment_id: uuid.UUID | None
    actions: list[RunActionOut]
    job_steps: list[JobStepOut] = []
    children: list[AgentRunOut] = []


@dataclass
class _Seen:
    detail: Detail
    task: RunTaskOut | None
    project: RunProjectOut | None


async def _seen(session: AsyncSession, ctx: Ctx, run: AgentRun) -> _Seen | None:
    """What the viewer may see of this run, or None when it doesn't exist for them."""
    t = run.trigger or {}
    task = project = None
    if t.get("task_id"):
        try:
            row, _pl, _role = await get_visible_task(session, ctx, uuid.UUID(t["task_id"]))
            task = RunTaskOut(id=row.id, key=task_key(row.number), title=row.title)
        except NotFound:
            pass
    if t.get("project_id"):
        try:
            p, _role = await get_visible_project(session, ctx, uuid.UUID(t["project_id"]))
            project = RunProjectOut(id=p.id, name=p.name)
        except NotFound:
            pass
    me = str(ctx.actor.id)
    if ctx.actor.is_admin or me in (t.get("requested_by"), t.get("for_user_id")):
        return _Seen("full", task, project)
    if task is not None or project is not None:
        return _Seen("summary", task, project)
    return None


async def _person(session: AsyncSession, raw: Any) -> RunPersonOut | None:
    if not raw:
        return None
    user = await session.get(User, uuid.UUID(str(raw)))
    return RunPersonOut(id=user.id, name=user.name) if user is not None else None


async def _actions(session: AsyncSession, run_id: uuid.UUID) -> list[AiAction]:
    rows = await session.execute(
        select(AiAction)
        .where(AiAction.source == "agent", AiAction.source_id == run_id)
        .order_by(AiAction.created_at)
    )
    return list(rows.scalars())


def _agent_out(agent: Agent) -> RunAgentOut:
    return RunAgentOut(id=agent.id, key=agent.key, name=agent.name, avatar=agent.avatar)


async def _summary(
    session: AsyncSession, run: AgentRun, agent: Agent, seen: _Seen, actions: list[AiAction]
) -> dict[str, Any]:
    t = run.trigger or {}
    return {
        "id": run.id,
        "agent": _agent_out(agent),
        "status": run.status,
        "trigger": str(t.get("type") or ""),
        "task": seen.task,
        "project": seen.project,
        "requested_by": await _person(session, t.get("requested_by") or t.get("for_user_id")),
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "steps": run.steps,
        "tokens_in": run.tokens_in,
        "tokens_out": run.tokens_out,
        "cost_usd": run.cost_usd,
        "error": run.error,
        "proposals": sum(1 for a in actions if a.decided_by != agent.user_id),
        "applied": sum(1 for a in actions if a.state in ("applied", "undone")),
        "mode": run.mode,
        "capability": run.capability,
        "parent_run_id": run.parent_run_id,
        "waiting_on": (run.waiting_on or {}).get("type")
        if run.status in ("waiting", "paused")
        else None,
        "progress": RunProgressOut.model_validate(run.progress) if run.progress else None,
        "attempt": run.attempt,
        "active_seconds": run.active_seconds,
    }


def _require_member(ctx: Ctx) -> None:
    if ctx.actor.role == "guest":
        raise Forbidden("Guests can't see agents")


async def list_runs(
    session: AsyncSession,
    ctx: Ctx,
    agent_id: uuid.UUID,
    *,
    status: str | None = None,
    trigger: str | None = None,
    limit: int = HISTORY_LIMIT,
) -> list[AgentRunOut]:
    """An agent's runs the viewer may see, newest first."""
    _require_member(ctx)
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.workspace_id != ctx.workspace_id:
        raise NotFound("Agent not found")
    if status is not None and status not in RUN_STATUSES:
        raise NotFound("Unknown status")
    stmt = select(AgentRun).where(AgentRun.agent_id == agent.id)
    if status is not None:
        stmt = stmt.where(AgentRun.status == status)
    if trigger is not None:
        stmt = stmt.where(AgentRun.trigger["type"].astext == trigger)
    rows = await session.execute(
        stmt.order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(limit * 4)
    )
    out: list[AgentRunOut] = []
    for run in rows.scalars():
        seen = await _seen(session, ctx, run)
        if seen is None:
            continue
        out.append(
            AgentRunOut(
                **await _summary(session, run, agent, seen, await _actions(session, run.id))
            )
        )
        if len(out) >= limit:
            break
    return out


async def _job_steps(session: AsyncSession, run: AgentRun, show_output: bool) -> list[JobStepOut]:
    rows = (
        await session.execute(
            select(AgentRunStep).where(AgentRunStep.run_id == run.id).order_by(AgentRunStep.seq)
        )
    ).scalars()
    out = []
    for r in rows:
        duration = (
            int((r.finished_at - r.started_at).total_seconds() * 1000)
            if r.started_at and r.finished_at
            else None
        )
        out.append(
            JobStepOut(
                seq=r.seq,
                key=r.key,
                kind=r.kind,
                status=r.status,
                started_at=r.started_at,
                finished_at=r.finished_at,
                duration_ms=duration,
                tokens_in=r.tokens_in,
                tokens_out=r.tokens_out,
                cost_usd=r.cost_usd,
                error=r.error if show_output or r.status == "failed" else None,
                output=r.output if show_output and r.output_ref is None else None,
            )
        )
    return out


def _classification(agent: Agent, packs: object) -> str:
    pack = (getattr(packs, "packs", None) or {}).get(agent.pack_key) if agent.pack_key else None
    return str(pack.manifest.data.classification) if pack is not None else "internal"


async def get_run(
    session: AsyncSession, ctx: Ctx, run_id: uuid.UUID, *, packs: object = None
) -> AgentRunDetailOut:
    _require_member(ctx)
    run = await session.get(AgentRun, run_id)
    if run is None or run.workspace_id != ctx.workspace_id:
        raise NotFound("Run not found")
    seen = await _seen(session, ctx, run)
    agent = await session.get(Agent, run.agent_id)
    if seen is None or agent is None:
        raise NotFound("Run not found")
    actions = await _actions(session, run.id)
    full = seen.detail == "full"
    trace = [
        RunStepOut(
            at=str(step.get("at") or ""),
            kind=str(step.get("kind") or ""),
            summary=str(step.get("summary") or "")
            if full or step.get("kind") in ("trigger", "policy", "limit", "error")
            else "",
            name=step.get("name"),
            ok=step.get("ok"),
        )
        for step in run.trace or []
    ]
    output = run.output or {}
    comment = output.get("comment_id")
    job_steps: list[JobStepOut] = []
    children: list[AgentRunOut] = []
    if run.mode == "job":
        # spec §4.6/§8.5: outputs for full viewers; a financial or personal pack's only for
        # people who can see the job's task
        classified = _classification(agent, packs) in ("financial", "personal")
        show = full and (not classified or seen.task is not None)
        job_steps = await _job_steps(session, run, show)
        kids = (
            await session.execute(
                select(AgentRun)
                .where(AgentRun.parent_run_id == run.id)
                .order_by(AgentRun.created_at, AgentRun.id)
            )
        ).scalars()
        for kid in kids:
            kid_seen = await _seen(session, ctx, kid) or seen
            children.append(AgentRunOut(**await _summary(session, kid, agent, kid_seen, [])))
    return AgentRunDetailOut(
        **await _summary(session, run, agent, seen, actions),
        detail=seen.detail,
        trace=trace,
        answer=str(output.get("text")) if full and output.get("text") else None,
        comment_id=uuid.UUID(comment) if comment and seen.task is not None else None,
        actions=[
            RunActionOut(
                id=a.id,
                summary=a.summary if full or a.proposed_for == ctx.actor.id else "",
                state=a.state,
                risk=a.risk,
                proposed_for=await _person(session, a.proposed_for),
                mine=a.proposed_for == ctx.actor.id and a.decided_by != agent.user_id,
            )
            for a in actions
        ],
        job_steps=job_steps,
        children=children,
    )
