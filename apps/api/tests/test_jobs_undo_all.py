"""Phase 7.6 S76-02 (spec §4.3, §4.7): "Undo everything <agent> did" and the job controls over the
API. Every activity row a job and its children write carries their ``request_id``; undoing the job
reverses them newest first with the caller's permissions and lists what it had to leave."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.packs.loader import TEST_PACKS_DIR, _load_test_pack
from momentum.app import create_app
from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.domain.comments.models import Comment
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from tests.ai_fixtures import World, world
from tests.helpers import Clients
from tests.jobs_env import JobsEnv

_ = world
B = "/api/v1"


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
    _load_test_pack(TEST_PACKS_DIR / "failer")
    module = sys.modules["momentum_test_pack_failer"]
    module.SWITCH.update(fail=False, crash=False)
    module.CALLS.clear()
    return module


async def _task(env: JobsEnv, task_id: Any) -> Task:
    async with env.uow.transaction() as s:
        row = await s.get(Task, task_id, populate_existing=True)
        assert row is not None
        return row


async def test_undo_everything_a_job_did(
    make_env: Callable[..., JobsEnv], world: World, failer: Any
) -> None:
    env = make_env()
    await env.install("failer")
    title = world.copy.title
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    result = (await env.run(run_id)).output or {}
    subtask_id = result["result"]["subtask"]
    async with env.uow.transaction() as s:
        rows = list(
            (
                await s.execute(
                    select(Activity).where(
                        Activity.request_id == str((await env.run(run_id)).request_id)
                    )
                )
            ).scalars()
        )
    assert {r.verb for r in rows} >= {"comment.created", "task.updated", "task.created"}

    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        lena = await clients("lena")  # can see the task, didn't ask, not an admin
        r = await lena.post(f"{B}/agents/runs/{run_id}/undo")
        assert r.status_code == 403, r.text
        tom = await clients("tom")  # can't see the job at all
        r = await tom.post(f"{B}/agents/runs/{run_id}/undo")
        assert r.status_code in (403, 404), r.text
        ravi = await clients("ravi")
        r = await ravi.post(f"{B}/agents/runs/{run_id}/undo")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["undone"] >= 3 and body["skipped"] == []
        detail = (await ravi.get(f"{B}/agents/runs/{run_id}")).json()
        assert detail["trace"][-1]["kind"] == "undo_all"
        await clients.close()

    assert (await _task(env, world.copy.id)).title == title
    assert (await _task(env, subtask_id)).deleted_at is not None
    async with env.uow.transaction() as s:
        live = list(
            (
                await s.execute(
                    select(Comment).where(
                        Comment.task_id == world.copy.id, Comment.deleted_at.is_(None)
                    )
                )
            ).scalars()
        )
    assert live == []


async def test_changes_someone_edited_since_are_left_and_listed(
    make_env: Callable[..., JobsEnv], world: World, failer: Any
) -> None:
    env = make_env()
    await env.install("failer")
    run_id = await env.start(task=world.copy)
    await env.drain()
    async with env.uow.transaction() as s:  # a person renames the task after the agent did
        await tasks.update_task(s, world.ravi, world.copy.id, {"title": "Ravi's own title"})
    from momentum.agents.jobs import control

    async with env.uow.transaction() as s:
        result = await control.undo_all(s, world.ravi, run_id)
    assert result.undone >= 2
    assert [x["verb"] for x in result.skipped] == ["task.updated"]
    assert (await _task(env, world.copy.id)).title == "Ravi's own title"


async def test_the_controls_over_the_api(
    make_env: Callable[..., JobsEnv], world: World, failer: Any
) -> None:
    env = make_env()
    await env.install("failer")
    failer.SWITCH["fail"] = True
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["failed"]
    failer.SWITCH["fail"] = False
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        ravi = await clients("ravi")
        detail = (await ravi.get(f"{B}/agents/runs/{run_id}")).json()
        assert detail["mode"] == "job" and detail["status"] == "failed"
        assert [s["key"] for s in detail["job_steps"]] == ["comment", "rename", "subtask", "last"]
        assert detail["job_steps"][-1]["status"] == "failed"
        assert detail["job_steps"][-1]["error"].startswith("RuntimeError")
        r = await ravi.post(f"{B}/agents/runs/{run_id}/retry")
        assert r.status_code == 200 and r.json()["status"] == "queued", r.text
        r = await ravi.post(f"{B}/agents/runs/{run_id}/pause")
        assert r.status_code == 403  # admins only
        admin = await clients("admin")
        r = await admin.post(f"{B}/agents/runs/{run_id}/pause")
        assert r.json()["status"] == "paused"
        r = await admin.post(f"{B}/agents/runs/{run_id}/resume")
        assert r.json()["status"] == "queued"
        r = await ravi.post(f"{B}/agents/runs/{run_id}/cancel")
        assert r.json()["status"] == "cancelled"
        r = await ravi.post(f"{B}/agents/runs/{run_id}/cancel")
        assert r.status_code == 409
        await clients.close()
