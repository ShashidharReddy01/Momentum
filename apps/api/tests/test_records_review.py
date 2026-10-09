"""Phase 7.6 S76-08 (spec §12.4-§12.5): what the review screen and the Records tab need from the
API. Record types with their form schema and counts, the source file's pages and sizes for the
page viewer, what a viewer may do, saves that undo, a bulk status change as one undoable batch,
and an entity's activity timeline."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.app import create_app
from momentum.core.db import UnitOfWork
from momentum.domain.records import service as records
from tests.ai_fixtures import World, world
from tests.helpers import Clients
from tests.jobs_env import JobsEnv
from tests.test_records import _agent_ctx, _env, _make, bill

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


async def test_types_detail_flags_saves_and_bulk_status(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env, impl = await _env(make_env)
    first = await _make(env, world, impl)
    second = await _make(env, world, impl, number="INV-0042")
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        app.state.momentum.packs = env.packs
        clients = Clients(app)
        ravi = await clients("ravi")

        types = (
            await ravi.get(f"{B}/records/types", params={"project_id": str(world.project.id)})
        ).json()["data"]
        [bill_type] = [t for t in types if t["key"] == "echo_bill"]
        assert bill_type["count"] == 2 and bill_type["label"] == "Echo bill"
        assert "properties" in bill_type["schema"]
        assert bill_type["display"]["columns"][:2] == ["vendor.name", "number"]

        detail = (await ravi.get(f"{B}/records/{first.id}")).json()
        assert detail["can_edit"] is True
        lena = await clients("lena")
        theirs = await lena.get(f"{B}/records/{first.id}")
        if theirs.status_code == 200:  # a viewer of the project can look but not change
            assert theirs.json()["can_edit"] is False and theirs.json()["can_decide"] is False

        saved = await ravi.patch(
            f"{B}/records/{first.id}",
            json={
                "ops": [{"op": "set", "path": "number", "value": "INV-9"}],
                "expected_version": 1,
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["activity_id"]
        undo = await ravi.post(f"{B}/undo", json={"activity_id": saved.json()["activity_id"]})
        assert undo.status_code == 200, undo.text
        back = (await ravi.get(f"{B}/records/{first.id}")).json()
        assert back["data"]["number"] == "INV-0041"

        bulk = await ravi.post(
            f"{B}/records/status",
            json={"ids": [str(first.id), str(second.id)], "status": "void", "reason": "Duplicates"},
        )
        assert bulk.status_code == 200, bulk.text
        assert bulk.json()["updated"] == 2 and bulk.json()["batch_id"]
        statuses = {
            (await ravi.get(f"{B}/records/{i}")).json()["status"] for i in (first.id, second.id)
        }
        assert statuses == {"void"}
        again = (
            await ravi.post(f"{B}/records/status", json={"ids": [str(first.id)], "status": "void"})
        ).json()
        assert again["updated"] == 0 and again["skipped"][0]["reason"].startswith("Already")
        one_undo = await ravi.post(f"{B}/undo", json={"batch_id": bulk.json()["batch_id"]})
        assert one_undo.status_code == 200, one_undo.text
        statuses = {
            (await ravi.get(f"{B}/records/{i}")).json()["status"] for i in (first.id, second.id)
        }
        assert "void" not in statuses
        await clients.close()


async def test_the_source_lists_pages_with_their_sizes(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    from PIL import Image

    from momentum.agents.extensions import attach_file

    env, impl = await _env(make_env)
    png = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(png, "PNG")
    async with env.uow.transaction() as s:
        att = await attach_file(
            s, world.ravi, env.settings, world.copy.id, "bill.png", png.getvalue(), "image/png"
        )
    agent = await _agent_ctx(env)
    async with env.uow.transaction() as s:
        r = await records.create_record(
            s,
            agent,
            impl,
            project_id=world.project.id,
            task_id=world.copy.id,
            data=bill(),
            source_attachment_id=att,
        )
        no_file = await records.create_record(
            s, agent, impl, project_id=world.project.id, data=bill(number="X-1")
        )
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        ravi = await clients("ravi")
        src = (await ravi.get(f"{B}/records/{r.id}/source")).json()
        assert src["filename"] == "bill.png" and src["mime"] == "image/png"
        assert src["pages"] == [{"n": 1, "width": 400.0, "height": 300.0}]
        assert (await ravi.get(f"{B}/records/{no_file.id}/source")).status_code == 404
        await clients.close()


async def test_an_entitys_activity(make_env: Callable[..., JobsEnv], world: World) -> None:
    from momentum.domain.entities import service as entities

    env, _impl = await _env(make_env)
    vendor_type = env.packs.packs["echo"].entity_type("echo_vendor")
    async with env.uow.transaction() as s:
        e = await entities.create_entity(
            s, world.ravi, vendor_type, pack_key="echo", name="Acme Ltd"
        )
    async with env.uow.transaction() as s:
        await entities.add_alias(s, world.ravi, e.id, "ACME Limited")
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        ravi = await clients("ravi")
        rows = (await ravi.get(f"{B}/entities/{e.id}/activity")).json()["data"]
        assert [r["verb"] for r in rows][:2] == ["entity.updated", "entity.created"]
        await clients.close()
