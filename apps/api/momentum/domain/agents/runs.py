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


async def enqueue_run(
    session: AsyncSession, agent: Agent, trigger: dict[str, Any], dedupe_key: str | None
) -> uuid.UUID | None:
    """Queue a run. With a ``dedupe_key`` the same trigger delivered twice queues once: the
    second insert is ignored and ``None`` is returned."""
    stmt = (
        insert(AgentRun)
        .values(
            id=new_id(),
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            trigger=trigger,
            dedupe_key=dedupe_key,
            status="queued",
            steps=0,
            input={},
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
    """What a run is about, for "one active run per agent per entity"."""
    t = run.trigger or {}
    for key in ("task_id", "project_id", "for_user_id"):
        if t.get(key):
            return f"{key}:{t[key]}"
    return None


async def claim_runs(session: AsyncSession, *, timeout_s: int, limit: int = CLAIM_BATCH) -> Claimed:
    """Mark the oldest queued runs ``running`` and return their ids (the caller commits, so a
    second worker can't take them; claimers take turns). A run is held back while the same agent
    is already running on the same entity. Runs stuck in ``running`` past the timeout are failed,
    never retried blind: a run may have written already."""
    await session.execute(select(func.pg_advisory_xact_lock(CLAIM_LOCK)))
    now = datetime.now(UTC)
    timed_out = await session.execute(
        update(AgentRun)
        .where(
            AgentRun.status == "running",
            AgentRun.started_at < now - timedelta(seconds=timeout_s) - STALE_MARGIN,
        )
        .values(status="failed", error="The run didn't finish in time", finished_at=now)
        .returning(AgentRun.id)
    )
    stale = len(timed_out.all())
    running = {
        (r.agent_id, run_entity(r))
        for r in (
            await session.execute(select(AgentRun).where(AgentRun.status == "running"))
        ).scalars()
    }
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
    for run in queued:
        slot = (run.agent_id, run_entity(run))
        if slot[1] is not None and slot in running:
            continue
        running.add(slot)
        ids.append(run.id)
        if len(ids) >= limit:
            break
    if ids:
        await session.execute(
            update(AgentRun).where(AgentRun.id.in_(ids)).values(status="running", started_at=now)
        )
    return Claimed(ids, stale)


async def recent_statuses(session: AsyncSession, agent_id: uuid.UUID, n: int) -> list[str]:
    rows = await session.execute(
        select(AgentRun.status)
        .where(AgentRun.agent_id == agent_id, AgentRun.finished_at.is_not(None))
        .order_by(AgentRun.finished_at.desc())
        .limit(n)
    )
    return list(rows.scalars())
