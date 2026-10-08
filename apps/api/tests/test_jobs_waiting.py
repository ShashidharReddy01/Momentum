"""Phase 7.6 S76-02 (spec §4.2-4.5): jobs that wait. Children (spawn / gather, at most
``limits.concurrency`` at a time, the parent not holding the worker), timers, events, cancel, pause
and resume, an agent switched off and on, maximum age, and the ``run:<id>`` realtime channel."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.jobs import control
from momentum.core.db import UnitOfWork
from momentum.core.errors import DomainError, Forbidden
from momentum.core.events import OutboxEvent
from momentum.domain.agents import service
from momentum.domain.agents.models import AgentRun
from momentum.domain.agents.schemas import AgentPatchIn
from momentum.domain.notifications.models import Notification
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from momentum.realtime.router import authorize_channel
from momentum.sdk import Job
from tests.ai_fixtures import REG, World, world
from tests.helpers import ctx_for
from tests.jobs_env import JobsEnv

_ = world


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


async def test_a_parent_with_20_children_runs_4_at_a_time_and_finishes(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("spawner")
    run_id = await env.start(task=world.copy, text="")
    statuses = await env.drain()
    parent = await env.run(run_id)
    assert parent.status == "succeeded", (parent.error, statuses)
    assert parent.output == {"result": {"total": sum(i * i for i in range(20)), "failed": []}}
    children = await env.children(run_id)
    assert len(children) == 20 and {c.status for c in children} == {"succeeded"}
    # never more than the pack's concurrency (4) of one parent's children in a round
    child_ids = {c.id for c in children}
    assert max(len([r for r in rnd if r in child_ids]) for rnd in env.rounds) == 4
    # each child got its own subtask, assigned to the agent
    async with env.uow.transaction() as s:
        subtasks = list(
            (await s.execute(select(Task).where(Task.parent_id == world.copy.id))).scalars()
        )
    assert len(subtasks) == 20 and {t.assignee_id for t in subtasks} == {env.agent.user_id}
    assert parent.progress == {"done": 20, "total": 20, "label": "Squared"}
    # the parent waited (freeing the worker) rather than holding a slot
    assert statuses.count("waiting") >= 1


async def test_a_failing_child_fails_only_itself(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def square(job: Job) -> int:
        x = int(job.input["x"])

        async def calc() -> int:
            if x == 2:
                raise ValueError("two is unlucky")
            return x * x

        return await job.step("square", calc)

    env = make_env()
    base = env.packs.packs["spawner"]
    env.use("spawner", capabilities={**base.capabilities, "square": square})
    await env.install("spawner")
    run_id = await env.start(task=world.copy)
    async with env.uow.transaction() as s:
        run = await s.get(AgentRun, run_id)
        assert run is not None
        run.input = {"n": 4}
    await env.drain()
    parent = await env.run(run_id)
    assert parent.status == "succeeded"
    assert parent.output == {"result": {"total": 0 + 1 + 9, "failed": ["item:2"]}}


async def test_sleep_until_wakes_on_time(make_env: Callable[..., JobsEnv], world: World) -> None:
    async def run(job: Job) -> str:
        start = await job.now("start")
        await job.sleep_until("nap", start + timedelta(hours=3))
        return "rested"

    env = make_env()
    env.use("failer", run=run)
    await env.install("failer")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["waiting"]
    run = await env.run(run_id)
    assert run.waiting_on is not None and run.waiting_on["type"] == "timer"
    assert run.resume_at is not None
    assert (await env.tick(datetime.now(UTC) + timedelta(hours=1))).woken == 0
    assert (await env.tick(datetime.now(UTC) + timedelta(hours=4))).woken == 1
    assert await env.drain() == ["succeeded"]


async def test_wait_for_event_resumes_with_the_event(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> str:
        event = await job.wait_for_event("done", "task.completed", task_id=job.task_id)
        return str(event["type"])

    env = make_env()
    env.use("failer", run=run)
    await env.install("failer")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["waiting"]
    async with env.uow.transaction() as s:  # an unrelated task completing doesn't wake it
        await tasks.set_completed(s, world.ravi, world.faq.id, True)
    assert await env.drain() == []
    async with env.uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, world.copy.id, True)
    assert await env.drain() == ["succeeded"]
    assert (await env.run(run_id)).output == {"result": "task.completed"}


async def test_cancel_stops_the_job_and_its_children(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("spawner")
    run_id = await env.start(task=world.copy)
    await env.tick()
    from momentum.domain.agents.runs import claim_runs

    async with env.uow.transaction() as s:  # one round: the parent spawns and waits
        claimed = await claim_runs(s, timeout_s=60)
    from momentum.agents.jobs.engine import execute_job

    assert (
        await execute_job(env.uow.transaction, env.llm, env.settings, env.packs, claimed.run_ids[0])
        == "waiting"
    )
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden):  # a viewer who didn't ask can't
            await control.cancel(s, world.lena, run_id)
    async with env.uow.transaction() as s:
        await control.cancel(s, world.ravi, run_id)
    assert (await env.run(run_id)).status == "cancelled"
    assert {c.status for c in await env.children(run_id)} == {"cancelled"}
    assert await env.drain() == []


async def test_pause_and_resume(make_env: Callable[..., JobsEnv], world: World) -> None:
    env = make_env()
    await env.install("spawner")
    run_id = await env.start(task=world.copy)
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden):
            await control.pause(s, world.ravi, run_id)  # admins only
        await control.pause(s, admin, run_id)
    assert await env.drain() == []  # a paused job isn't claimed
    async with env.uow.transaction() as s:
        await control.resume(s, admin, run_id)
    await env.drain()
    assert (await env.run(run_id)).status == "succeeded"


async def test_switching_the_agent_off_pauses_its_jobs_and_on_resumes_them(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> str:
        start = await job.now("start")
        await job.sleep_until("nap", start + timedelta(hours=1))
        return "done"

    env = make_env()
    env.use("failer", run=run)
    await env.install("failer")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["waiting"]
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        await service.update_agent(s, admin, env.agent.id, AgentPatchIn(enabled=False), REG.names)
    run = await env.run(run_id)
    assert run.status == "paused" and (run.waiting_on or {}).get("type") == "agent_off"
    await env.tick(datetime.now(UTC) + timedelta(hours=2))
    assert (await env.run(run_id)).status == "paused"  # not woken while off
    async with env.uow.transaction() as s:
        await service.update_agent(s, admin, env.agent.id, AgentPatchIn(enabled=True), REG.names)
    await env.tick(datetime.now(UTC) + timedelta(hours=2))
    assert "succeeded" in await env.drain()


async def test_a_job_past_its_maximum_age_expires_and_the_person_is_told(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> None:
        await job.wait_for_event("never", "task.completed", task_id=job.task_id)

    env = make_env()
    env.use("failer", run=run)
    await env.install("failer")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["waiting"]
    stats = await env.tick(datetime.now(UTC) + timedelta(days=31))
    assert stats.expired == 1
    run = await env.run(run_id)
    assert run.status == "expired" and "longer than 30 days" in (run.error or "")
    async with env.uow.transaction() as s:
        told = await s.scalar(
            select(Notification).where(
                Notification.user_id == world.ravi.actor.id, Notification.entity_id == run_id
            )
        )
    assert told is not None


async def test_progress_and_waiting_events_reach_the_run_channel(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("spawner")
    run_id = await env.start(task=world.copy)
    await env.drain()
    async with env.uow.transaction() as s:
        types = {
            e.type
            for e in (
                await s.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.payload["channels"].op("?")(f"run:{run_id}")
                    )
                )
            ).scalars()
        }
    assert {
        "agent_run.step",
        "agent_run.waiting",
        "agent_run.resumed",
        "agent_run.progress",
    } <= types
    assert "agent_run.finished" in types
    async with env.uow.transaction() as s:
        await authorize_channel(s, world.ravi, f"run:{run_id}")
        with pytest.raises(DomainError):
            await authorize_channel(s, world.tom, f"run:{run_id}")  # can't see the task
