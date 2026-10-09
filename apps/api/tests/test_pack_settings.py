"""Phase 7.6 S76-05 (spec §8.3): pack settings. Defaults, then workspace values, then a project's,
field by field; validated against the pack's model; who may change which level (admins and
stewards for the workspace, project admins for theirs); undo; ``job.settings()``; and the
``stewards`` / ``approvers`` routes for agents' questions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.app import create_app
from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden, ValidationFailed
from momentum.core.undo import undo
from momentum.domain.asks.models import Ask
from momentum.domain.pack_settings import service as settings
from momentum.sdk import Job
from tests.ai_fixtures import World, world
from tests.helpers import Clients, ctx_for
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


async def test_layers_permissions_validation_and_undo(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    model = env.packs.packs["echo"].settings
    admin = await ctx_for(env.uow, env.settings, "admin")
    pid = world.project.id
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden):
            await settings.put_values(s, world.ravi, model, "echo", None, {"threshold": 5})
        await settings.put_values(
            s, admin, model, "echo", None, {"threshold": 50, "stewards": [str(world.ravi.actor.id)]}
        )
    async with env.uow.transaction() as s:  # now a steward: may change the workspace values
        await settings.put_values(
            s,
            world.ravi,
            model,
            "echo",
            None,
            {"threshold": 60, "stewards": [str(world.ravi.actor.id)]},
        )
        # ravi owns the project: may set its values; a project value overrides one field only
        await settings.put_values(s, world.ravi, model, "echo", pid, {"tone": "friendly"})
        eff = await settings.effective_values(s, model, admin.workspace_id, "echo", pid)
        ws_only = await settings.effective_values(s, model, admin.workspace_id, "echo", None)
    assert (eff["threshold"], eff["tone"]) == (60, "friendly")
    assert (ws_only["threshold"], ws_only["tone"]) == (60, "plain")
    async with env.uow.transaction() as s:
        with pytest.raises(ValidationFailed, match="Unknown setting"):
            await settings.put_values(s, admin, model, "echo", None, {"colour": "red"})
        with pytest.raises(ValidationFailed):
            await settings.put_values(s, admin, model, "echo", None, {"threshold": -1})
        with pytest.raises(Forbidden):  # a viewer of the project isn't its admin
            await settings.put_values(s, world.lena, model, "echo", pid, {"tone": "plain"})
        act = await s.scalar(
            select(Activity.id)
            .where(Activity.verb == "pack_settings.updated")
            .order_by(Activity.id.desc())  # time-ordered ids (created_at is per transaction)
            .limit(1)
        )
    async with env.uow.transaction() as s:
        await undo(s, world.ravi, activity_id=act)  # the project's tone change
        eff = await settings.effective_values(s, model, admin.workspace_id, "echo", pid)
    assert eff["tone"] == "plain"


async def test_the_settings_api(make_env: Callable[..., JobsEnv], world: World) -> None:
    env = make_env()
    await env.install("echo")
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        app.state.momentum.packs = env.packs
        clients = Clients(app)
        admin = await clients("admin")
        url = f"{B}/agents/{env.agent.id}/settings"
        got = (await admin.get(url)).json()
        assert got["form"]["properties"]["threshold"]["ui"] == "int"
        assert got["effective"]["threshold"] == 100 and got["can_edit"] is True
        put = await admin.put(url, json={"values": {"threshold": 7}})
        assert put.status_code == 200, put.text
        assert put.json()["workspace"] == {"threshold": 7}
        undo = await admin.post(f"{B}/undo", json={"activity_id": put.json()["activity_id"]})
        assert undo.status_code == 200, undo.text
        assert (await admin.get(url)).json()["workspace"] == {}
        ana = await clients("ana")
        assert (await ana.get(url)).json()["can_edit"] is False
        assert (await ana.put(url, json={"values": {"threshold": 1}})).status_code == 403
        bad = await admin.put(url, json={"values": {"threshold": "lots"}})
        assert bad.status_code == 422
        await clients.close()


async def test_a_job_reads_its_projects_settings(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> dict[str, Any]:
        s = await job.settings()
        return {"threshold": s.threshold, "tone": s.tone}

    env = make_env()
    env.use("echo", run=run)
    await env.install("echo")
    admin = await ctx_for(env.uow, env.settings, "admin")
    model = env.packs.packs["echo"].settings
    async with env.uow.transaction() as s:
        await settings.put_values(s, admin, model, "echo", None, {"threshold": 9})
        await settings.put_values(s, admin, model, "echo", world.project.id, {"tone": "friendly"})
    async with env.uow.transaction() as s:
        from momentum.agents.triggers import request_run

        run_id = await request_run(
            s, world.ravi, env.agent, project_id=world.project.id, packs=env.packs
        )
    assert await env.drain() == ["succeeded"]
    assert ((await env.run(run_id)).output or {})["result"] == {"threshold": 9, "tone": "friendly"}


async def test_stewards_and_approvers_are_routes_for_questions(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def run(job: Job) -> Any:
        return await job.ask(
            "q",
            kind="confirm",
            title="Approve?",
            route=str(job.input.get("text") or "approver"),
            default_on_expiry={"action": "fail"},
        )

    env = make_env()
    env.use("echo", run=run)
    await env.install("echo")
    admin = await ctx_for(env.uow, env.settings, "admin")
    model = env.packs.packs["echo"].settings
    from momentum.domain.projects.service import add_member

    async with env.uow.transaction() as s:
        await add_member(s, world.ravi, world.project.id, world.ana.actor.id, "editor")
        await settings.put_values(
            s,
            admin,
            model,
            "echo",
            None,
            {"approvers": [str(world.ana.actor.id)], "stewards": [str(world.ravi.actor.id)]},
        )
    first = await env.start(task=world.copy, text="approver")
    second = await env.start(task=world.faq, text="stewards")
    assert sorted(await env.drain()) == ["waiting", "waiting"]
    async with env.uow.transaction() as s:
        asks = {a.run_id: a.to_user_ids for a in (await s.execute(select(Ask))).scalars()}
    assert asks[first] == [world.ana.actor.id]
    assert asks[second] == [world.ravi.actor.id]
