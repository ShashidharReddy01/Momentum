"""Phase 7.6 S76-02 (spec §4.2-4.3): durable jobs replay. A step runs once; a job killed between
steps resumes without re-running finished steps or duplicating their effects; retry starts again
from the failed step; outputs come back as their annotated types; the pack rules (unique keys,
effects only inside steps and only when declared) are enforced."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.jobs import control
from momentum.agents.packs.loader import TEST_PACKS_DIR, _load_test_pack
from momentum.core.db import UnitOfWork
from momentum.domain.comments.models import Comment
from momentum.sdk import Job, step
from tests.ai_fixtures import World, world
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


@pytest.fixture
def failer() -> Any:
    """The failer test pack's module (its SWITCH and CALLS), reset per test."""
    _load_test_pack(TEST_PACKS_DIR / "failer")  # the same module the loader uses
    module = sys.modules["momentum_test_pack_failer"]
    module.SWITCH.update(fail=False, crash=False)
    module.CALLS.clear()
    return module


async def _comments(env: JobsEnv, task_id: uuid.UUID) -> list[Comment]:
    async with env.uow.transaction() as s:
        return list(
            (
                await s.execute(
                    select(Comment).where(Comment.task_id == task_id, Comment.deleted_at.is_(None))
                )
            ).scalars()
        )


async def test_a_job_runs_its_steps_once_and_succeeds(
    make_env: Callable[..., JobsEnv], world: World, failer: Any
) -> None:
    env = make_env()
    await env.install("failer")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    run = await env.run(run_id)
    assert run.mode == "job" and run.pack_version == "1.0.0" and run.status == "succeeded"
    assert run.output is not None and run.output["result"]["answer"] == 42
    assert [s.key for s in await env.steps(run_id)] == ["comment", "rename", "subtask", "last"]
    assert all(s.status == "done" for s in await env.steps(run_id))
    assert dict(failer.CALLS) == {"comment": 1, "rename": 1, "subtask": 1, "last": 1}
    assert [c.body for c in await _comments(env, world.copy.id)]  # the effect landed
    assert any(t["kind"] == "log" for t in run.trace)


async def test_a_job_killed_between_steps_resumes_without_repeating_them(
    make_env: Callable[..., JobsEnv], world: World, failer: Any
) -> None:
    env = make_env()
    await env.install("failer")
    copy_id = world.copy.id  # the crash's rollback expires every loaded object
    run_id = await env.start(task=world.copy)
    failer.SWITCH["crash"] = True
    with pytest.raises(failer.Crash):
        await env.drain()
    run = await env.run(run_id)
    assert run.status == "running"  # the worker "died" mid-job
    assert len(await _comments(env, copy_id)) == 1  # the first step's effect committed
    failer.SWITCH["crash"] = False
    # the next tick finds the dead pass and requeues it (replay makes that safe)
    stats = await env.tick(datetime.now(UTC) + timedelta(days=1))
    assert stats.requeued == 1
    assert await env.drain() == ["succeeded"]
    assert dict(failer.CALLS) == {"comment": 1, "rename": 2, "subtask": 1, "last": 1}
    assert len(await _comments(env, copy_id)) == 1  # no duplicated effect
    assert (await env.run(run_id)).attempt == 1


async def test_retry_starts_again_from_the_failed_step(
    make_env: Callable[..., JobsEnv], world: World, failer: Any
) -> None:
    env = make_env()
    await env.install("failer")
    run_id = await env.start(task=world.copy)
    failer.SWITCH["fail"] = True
    assert await env.drain() == ["failed"]
    run = await env.run(run_id)
    assert run.error is not None and run.error.startswith("Failed at last: RuntimeError")
    steps = {s.key: s.status for s in await env.steps(run_id)}
    assert steps == {"comment": "done", "rename": "done", "subtask": "done", "last": "failed"}
    failer.SWITCH["fail"] = False
    async with env.uow.transaction() as s:
        await control.retry(s, world.ravi, run_id)
    assert await env.drain() == ["succeeded"]
    assert dict(failer.CALLS) == {"comment": 1, "rename": 1, "subtask": 1, "last": 2}
    assert (await env.run(run_id)).attempt == 1


class Invoice(BaseModel):
    vendor: str
    total: float


@step
async def _read() -> Invoice:
    return Invoice(vendor="Acme", total=12.5)


async def test_outputs_replay_as_their_annotated_types(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    seen: list[Any] = []

    async def run(job: Job) -> str:
        invoice = await job.step("read", _read)
        started = await job.now("started")
        await job.sleep_until("nap", started + timedelta(hours=1))
        seen.append((type(invoice), type(started)))
        return invoice.vendor

    env = make_env()
    env.use("failer", run=run)
    await env.install("failer")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["waiting"]
    await env.tick(datetime.now(UTC) + timedelta(hours=2))
    assert await env.drain() == ["succeeded"]
    assert seen == [(Invoice, datetime)]  # the second pass got a model and a datetime back
    assert (await env.run(run_id)).output == {"result": "Acme"}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("twice", "used twice"),
        ("outside", "only be called inside a step"),
        ("undeclared", "failer may not attachments.create"),
        ("nested", "can't nest"),
    ],
)
async def test_the_pack_rules_are_enforced(
    make_env: Callable[..., JobsEnv], world: World, body: str, message: str
) -> None:
    async def one() -> int:
        return 1

    async def run(job: Job) -> None:
        assert job.task_id is not None
        if body == "twice":
            await job.step("same", one)
            await job.step("same", one)
        elif body == "outside":
            await job.effects.comments.create(job.task_id, "not in a step")
        elif body == "undeclared":

            async def attach() -> None:
                assert job.task_id is not None
                await job.effects.attachments.create(job.task_id, "x.txt", b"x")

            await job.step("attach", attach)
        else:

            async def outer() -> int:
                return await job.step("inner", one)

            await job.step("outer", outer)

    env = make_env()
    env.use("failer", run=run)
    await env.install("failer")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["failed"]
    error = (await env.run(run_id)).error or ""
    assert message in error, error


async def test_legacy_runs_stay_one_shot(make_env: Callable[..., JobsEnv], world: World) -> None:
    """Every Phase 5 agent keeps ``mode='oneshot'`` and runs exactly as before; only a pack
    agent's runs are jobs."""
    from momentum.domain.agents.models import AgentRun
    from momentum.domain.agents.runs import enqueue_run
    from momentum.domain.agents.schemas import AgentDefinition
    from tests.ai_fixtures import REG
    from tests.helpers import ctx_for

    env = make_env()
    admin = await ctx_for(env.uow, env.settings, "admin")
    helper = AgentDefinition.model_validate(
        {"key": "helper", "name": "Helper", "triggers": [{"type": "manual"}], "tools": ["get_task"]}
    )
    async with env.uow.transaction() as s:
        from momentum.domain.agents import service

        [r] = await service.install_definitions(s, admin, [(helper, "host")], REG.names)
        legacy = await enqueue_run(s, r.agent, {"type": "manual"}, "manual:legacy")
    await env.install("failer")
    job = await env.start(task=world.copy)
    async with env.uow.transaction() as s:
        modes = dict((await s.execute(select(AgentRun.id, AgentRun.mode))).tuples().all())
    assert modes == {legacy: "oneshot", job: "job"}


async def test_a_pack_agent_assigned_a_task_gets_a_job_from_its_manifest_triggers(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    from momentum.agents.triggers import consume_events
    from momentum.domain.tasks import service as tasks

    env = make_env()
    await env.install("echo")  # triggers come from echo's manifest (assigned, manual)
    async with env.uow.transaction() as s:
        await consume_events(s, env.settings, packs=env.packs)  # start from now
    async with env.uow.transaction() as s:
        await tasks.update_task(s, world.ravi, world.copy.id, {"assignee_id": env.agent.user_id})
    async with env.uow.transaction() as s:
        assert (await consume_events(s, env.settings, packs=env.packs)).queued == 1
    assert await env.drain() == ["succeeded"]
    bodies = [str(c.body) for c in await _comments(env, world.copy.id)]
    assert any("Echo: nothing to echo" in b for b in bodies)


async def test_run_now_gives_a_pack_job_the_persons_text(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    run_id = await env.start(task=world.copy, text="hello there")
    assert (await env.run(run_id)).input == {"text": "hello there"}
    assert await env.drain() == ["succeeded"]
    assert (await env.run(run_id)).output == {"result": "hello there"}
