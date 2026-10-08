"""S5.1.2: agent run records: enqueue (deduplicated), claim, finish.

A run is a log of one agent execution, like ``rule_runs``: written by the trigger evaluation and
the runtime, never edited by people, so it records no activity of its own (the changes an agent
makes do, through the services it calls).

``trigger`` (jsonb) says why the run exists and what it is about:
``{type, event_id?, event_type?, task_id?, project_id?, comment_id?, requested_by?, for_user_id?,
fire_time?, external?, input?}``. ``requested_by`` is the person the result is for (proposals are
made to them); ``for_user_id`` makes the run act *on behalf of* that person (per-user agents such
as Pulse); ``external`` marks content from outside the workspace (forms, integrations), which
caps the agent's writes at ``confirm`` (ai-architecture §8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.ids import new_id
from momentum.domain.agents.models import Agent, AgentRun

CLAIM_BATCH = 10
# a run left `running` longer than its own timeout plus this margin died with its worker
STALE_MARGIN = timedelta(minutes=2)
# S7.3.1: claimers take turns (a transaction-scoped advisory lock), so a second worker sees the
# runs the first just started and never starts the same agent on the same entity beside it.
CLAIM_LOCK = 0x4D6F_0001


@dataclass(frozen=True)
class Claimed:
    run_ids: list[uuid.UUID]
    timed_out: int
    jobs: frozenset[uuid.UUID] = frozenset()  # the claimed runs that are durable jobs


async def enqueue_run(
    session: AsyncSession,
    agent: Agent,
    trigger: dict[str, Any],
    dedupe_key: str | None,
    *,
    capability: str | None = None,
    input: dict[str, Any] | None = None,
) -> uuid.UUID | None:
    """Queue a run. With a ``dedupe_key`` the same trigger delivered twice queues once: the
    second insert is ignored and ``None`` is returned. A pack agent's run is a durable job
    (Phase 7.6 S76-02); its input is the text a person gave, if any."""
    is_pack = agent.kind == "pack"
    stmt = (
        insert(AgentRun)
        .values(
            id=new_id(),
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            trigger=trigger,
            dedupe_key=dedupe_key,
            status="queued",
            mode="job" if is_pack else "oneshot",
            pack_version=agent.pack_version if is_pack else None,
            request_id=uuid.uuid4(),
            steps=0,
            capability=capability,
            input=input
            if input is not None
            else {"text": trigger["input"]}
            if is_pack and trigger.get("input")
            else {},
            trace=[],
            tokens_in=0,
            tokens_out=0,
            cost_usd=0,
        )
        .on_conflict_do_nothing(index_elements=["agent_id", "dedupe_key"])
        .returning(AgentRun.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def run_entity(run: AgentRun) -> str | None:
    """What a run is about, for "one active run per agent per entity". A child job has no slot of
    its own: its parent's ``concurrency`` limits it instead."""
    if run.parent_run_id is not None:
        return None
    t = run.trigger or {}
    for key in ("task_id", "project_id", "for_user_id"):
        if t.get(key):
            return f"{key}:{t[key]}"
    return None


async def claim_runs(
    session: AsyncSession,
    *,
    timeout_s: int,
    limit: int = CLAIM_BATCH,
    packs_enabled: bool = True,
) -> Claimed:
    """Mark the oldest queued runs ``running`` and return their ids (the caller commits, so a
    second worker can't take them; claimers take turns). A run is held back while the same agent
    is already running on the same entity, and a child job while its parent already has
    ``concurrency`` children running. One-shot runs stuck in ``running`` past the timeout are
    failed, never retried blind: a run may have written already (a job's dead pass is requeued by
    ``tick_jobs`` instead: replay makes that safe). With packs switched off, jobs wait."""
    await session.execute(select(func.pg_advisory_xact_lock(CLAIM_LOCK)))
    now = datetime.now(UTC)
    timed_out = await session.execute(
        update(AgentRun)
        .where(
            AgentRun.status == "running",
            AgentRun.mode == "oneshot",
            AgentRun.started_at < now - timedelta(seconds=timeout_s) - STALE_MARGIN,
        )
        .values(status="failed", error="The run didn't finish in time", finished_at=now)
        .returning(AgentRun.id)
    )
    stale = len(timed_out.all())
    active = list(
        (await session.execute(select(AgentRun).where(AgentRun.status == "running"))).scalars()
    )
    running = {(r.agent_id, run_entity(r)) for r in active}
    children: dict[uuid.UUID, int] = {}
    for r in active:
        if r.parent_run_id is not None:
            children[r.parent_run_id] = children.get(r.parent_run_id, 0) + 1
    queued = list(
        (
            await session.execute(
                select(AgentRun)
                .where(AgentRun.status == "queued")
                .order_by(AgentRun.created_at, AgentRun.id)
                .limit(limit * 5)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    ids: list[uuid.UUID] = []
    jobs: set[uuid.UUID] = set()
    for run in queued:
        if run.mode == "job" and not packs_enabled:
            continue
        slot = (run.agent_id, run_entity(run))
        if slot[1] is not None and slot in running:
            continue
        if run.parent_run_id is not None:
            cap = int((run.trigger or {}).get("concurrency") or 1)
            if children.get(run.parent_run_id, 0) >= cap:
                continue
            children[run.parent_run_id] = children.get(run.parent_run_id, 0) + 1
        running.add(slot)
        ids.append(run.id)
        if run.mode == "job":
            jobs.add(run.id)
        if len(ids) >= limit:
            break
    if ids:
        await session.execute(
            update(AgentRun).where(AgentRun.id.in_(ids)).values(status="running", started_at=now)
        )
    return Claimed(ids, stale, frozenset(jobs))


async def recent_statuses(session: AsyncSession, agent_id: uuid.UUID, n: int) -> list[str]:
    rows = await session.execute(
        select(AgentRun.status)
        .where(AgentRun.agent_id == agent_id, AgentRun.finished_at.is_not(None))
        .order_by(AgentRun.finished_at.desc())
        .limit(n)
    )
    return list(rows.scalars())


async def pause_jobs_of(session: AsyncSession, agent_id: uuid.UUID) -> int:
    """Phase 7.6 (spec §4.3): turning an agent off pauses its open jobs instead of failing them
    (what each was waiting on is kept, so an event that happens meanwhile isn't lost)."""
    rows = (
        await session.execute(
            select(AgentRun)
            .where(
                AgentRun.agent_id == agent_id,
                AgentRun.mode == "job",
                AgentRun.status.in_(("queued", "waiting")),
            )
            .with_for_update()
        )
    ).scalars()
    n = 0
    for run in rows:
        run.waiting_on = {"type": "agent_off", "was": run.waiting_on}
        run.status, run.resume_at = "paused", None
        n += 1
    return n


async def resume_jobs_of(session: AsyncSession, agent_id: uuid.UUID) -> int:
    """Turning the agent back on queues the jobs its switch-off paused (a pass replays to where
    the job stopped and waits again if it still has to). Jobs a person paused stay paused."""
    rows = (
        await session.execute(
            select(AgentRun)
            .where(
                AgentRun.agent_id == agent_id,
                AgentRun.mode == "job",
                AgentRun.status == "paused",
                AgentRun.waiting_on["type"].astext == "agent_off",
            )
            .with_for_update()
        )
    ).scalars()
    n = 0
    for run in rows:
        restore_from_pause(run)
        n += 1
    return n


def restore_from_pause(run: AgentRun) -> None:
    """Un-pause a job. A timer or event it was waiting on is waited on again (a timer keeps its
    time; an event that happened meanwhile was already recorded, so the job is queued); anything
    else is queued, and the next pass replays to where it stopped and waits again if it must."""
    was = (run.waiting_on or {}).get("was") or {}
    run.error = None
    if was.get("type") == "timer" and was.get("until"):
        run.status, run.waiting_on = "waiting", was
        run.resume_at = datetime.fromisoformat(str(was["until"]))
    elif was.get("type") == "event":
        run.status, run.waiting_on, run.resume_at = "waiting", was, None
    else:
        run.status, run.waiting_on, run.resume_at = "queued", None, None
