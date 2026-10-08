"""Phase 7.6 S76-02 (spec §4.3, §4.7): people controlling a job.

- **Retry from the failed step** (the person who asked, or a workspace admin): the failed step is
  cleared, ``attempt`` goes up, and the job is queued; finished steps replay.
- **Cancel** (the person who asked, a project admin, a workspace admin): the job and its open
  children stop. What's already written stays; "Undo everything" is offered.
- **Pause / resume** (workspace admins): a paused job isn't claimed. A pass that is running stops
  at its next step.
- **Undo everything a job did** (the person who asked, a project admin, a workspace admin): every
  activity row the job and its children wrote (they share the job's ``request_id``s) is undone,
  newest first, with the caller's permissions; rows that can't be undone are listed, not forced.

Like ``domain/agents/runs.py``, run rows are a log written by the platform: changing a job's state
records no activity of its own (the agent's changes do, through the services).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents.jobs.engine import _after_terminal, system_ctx
from momentum.agents.runs_view import _seen
from momentum.agents.triggers import task_project_ids
from momentum.core.activity import Activity
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, DomainError, Forbidden, NotFound
from momentum.core.undo import undo
from momentum.domain.access import get_visible_project, get_visible_task
from momentum.domain.agents.models import Agent, AgentRun, AgentRunStep
from momentum.domain.agents.runs import restore_from_pause

OPEN = ("queued", "running", "waiting", "paused")


async def _job(s: AsyncSession, ctx: Ctx, run_id: uuid.UUID) -> AgentRun:
    run = await s.get(AgentRun, run_id, with_for_update=True)
    if run is None or run.workspace_id != ctx.workspace_id or run.mode != "job":
        raise NotFound("Job not found")
    if await _seen(s, ctx, run) is None:  # a job you can't see doesn't exist for you
        raise NotFound("Job not found")
    return run


async def _is_project_admin(s: AsyncSession, ctx: Ctx, run: AgentRun) -> bool:
    t = run.trigger or {}
    project_ids: list[uuid.UUID] = []
    if t.get("project_id"):
        project_ids.append(uuid.UUID(str(t["project_id"])))
    if t.get("task_id"):
        try:
            task, _pl, _role = await get_visible_task(s, ctx, uuid.UUID(str(t["task_id"])))
            project_ids += await task_project_ids(s, task)
        except NotFound:
            pass
    for pid in project_ids:
        try:
            _project, role = await get_visible_project(s, ctx, pid)
        except NotFound:
            continue
        if role == "admin":
            return True
    return False


async def _require(s: AsyncSession, ctx: Ctx, run: AgentRun, *, project_admins: bool) -> None:
    if ctx.actor.is_admin:
        return
    if ctx.actor.id is not None and str(ctx.actor.id) == str(
        (run.trigger or {}).get("requested_by")
    ):
        return
    if project_admins and await _is_project_admin(s, ctx, run):
        return
    who = (
        "the person who asked, a project admin or" if project_admins else "the person who asked or"
    )
    raise Forbidden(f"Only {who} a workspace admin can do this")


async def _tree(s: AsyncSession, root: AgentRun) -> list[AgentRun]:
    """The job and all its descendants, parents first."""
    out, frontier = [root], [root.id]
    while frontier:
        children = list(
            (
                await s.execute(
                    select(AgentRun)
                    .where(AgentRun.parent_run_id.in_(frontier))
                    .order_by(AgentRun.created_at)
                    .with_for_update()
                )
            ).scalars()
        )
        out += children
        frontier = [c.id for c in children]
    return out


async def retry(s: AsyncSession, ctx: Ctx, run_id: uuid.UUID) -> AgentRun:
    run = await _job(s, ctx, run_id)
    await _require(s, ctx, run, project_admins=False)
    if run.status not in ("failed", "budget_exceeded"):
        raise Conflict("Only a failed job can be retried")
    await s.execute(
        delete(AgentRunStep).where(AgentRunStep.run_id == run.id, AgentRunStep.status != "done")
    )
    run.status, run.error, run.finished_at = "queued", None, None
    run.attempt += 1
    run.trace = [
        *(run.trace or []),
        {"at": datetime.now(UTC).isoformat(), "kind": "retry", "summary": "Retried"},
    ]
    await s.flush()
    return run


async def cancel(s: AsyncSession, ctx: Ctx, run_id: uuid.UUID) -> AgentRun:
    run = await _job(s, ctx, run_id)
    await _require(s, ctx, run, project_admins=True)
    if run.status not in OPEN:
        raise Conflict("This job has already ended")
    now = datetime.now(UTC)
    who = ctx.actor.name or "someone"
    for r in reversed(await _tree(s, run)):
        if r.status in OPEN:
            r.status, r.finished_at = "cancelled", now
            r.error = f"Cancelled by {who}"
            r.waiting_on = r.resume_at = None
    await s.flush()
    agent = await s.get(Agent, run.agent_id)
    await _after_terminal(s, ctx.settings, system_ctx(run.workspace_id, ctx.settings), run, agent)
    return run


async def pause(s: AsyncSession, ctx: Ctx, run_id: uuid.UUID) -> AgentRun:
    run = await _job(s, ctx, run_id)
    if not ctx.actor.is_admin:
        raise Forbidden("Only workspace admins can pause a job")
    if run.status not in ("queued", "running", "waiting"):
        raise Conflict(f"A {run.status} job can't be paused")
    run.waiting_on = {"type": "paused", "was": run.waiting_on, "by": str(ctx.actor.id)}
    run.status, run.resume_at = "paused", None
    await s.flush()
    return run


async def resume(s: AsyncSession, ctx: Ctx, run_id: uuid.UUID) -> AgentRun:
    run = await _job(s, ctx, run_id)
    if not ctx.actor.is_admin:
        raise Forbidden("Only workspace admins can resume a job")
    if run.status != "paused":
        raise Conflict("This job isn't paused")
    agent = await s.get(Agent, run.agent_id)
    if agent is None or not agent.enabled:
        raise Conflict("Turn the agent on first")
    restore_from_pause(run)
    await s.flush()
    return run


@dataclass
class UndoAllResult:
    undone: int = 0
    skipped: list[dict[str, Any]] = field(default_factory=list)


async def undo_all(s: AsyncSession, ctx: Ctx, run_id: uuid.UUID) -> UndoAllResult:
    run = await _job(s, ctx, run_id)
    await _require(s, ctx, run, project_admins=True)
    agent = await s.get(Agent, run.agent_id)
    if agent is None:
        raise NotFound("Job not found")
    tree = await _tree(s, run)
    if any(r.status == "running" for r in tree):
        raise Conflict("The job is working right now; cancel or pause it first")
    request_ids = [str(r.request_id) for r in tree]
    rows = list(
        (
            await s.execute(
                select(Activity)
                .where(
                    Activity.workspace_id == ctx.workspace_id,
                    Activity.request_id.in_(request_ids),
                    Activity.undone_at.is_(None),
                )
                .order_by(Activity.created_at.desc(), Activity.id.desc())
            )
        ).scalars()
    )
    result = UndoAllResult()
    undone: set[uuid.UUID] = set()
    for row in rows:
        if row.id in undone:
            continue  # undone as part of an earlier row's reversal
        await s.refresh(row)
        if row.undone_at is not None:
            continue
        savepoint = await s.begin_nested()
        try:
            for r in await undo(s, ctx, activity_id=row.id, also_by=agent.user_id):
                undone.add(r.id)
            await savepoint.commit()
            result.undone += 1
        except DomainError as e:
            await savepoint.rollback()
            result.skipped.append(
                {
                    "entity_type": row.entity_type,
                    "entity_id": str(row.entity_id),
                    "verb": row.verb,
                    "reason": e.detail,
                }
            )
    run.trace = [
        *(run.trace or []),
        {
            "at": datetime.now(UTC).isoformat(),
            "kind": "undo_all",
            "summary": f"{ctx.actor.name or 'Someone'} undid {result.undone} changes"
            + (f"; {len(result.skipped)} left as they are" if result.skipped else ""),
        },
    ]
    await s.flush()
    return result
