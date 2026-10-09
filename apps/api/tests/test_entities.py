"""Phase 7.6 S76-05 (spec §7.1): entities. Created by a job's declared effect; matching (tax id,
exact name or alias, trigram, candidates); bank details only as a fingerprint and last four
digits, and the fingerprint never in any API response; merge moves records and skills and undoes
cleanly; who may do what; nightly profiles."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.packs.profiles import compute_profiles
from momentum.app import create_app
from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden
from momentum.core.undo import undo
from momentum.domain.entities import service as entities
from momentum.domain.entities.models import Entity
from momentum.domain.records import service as records
from momentum.domain.records.models import Record
from momentum.domain.records.schemas import SetStatusOp
from momentum.domain.skills import service as skills
from momentum.domain.skills.models import Skill
from momentum.domain.users.models import User
from momentum.sdk import Job, step
from tests.ai_fixtures import World, world
from tests.helpers import Clients, ctx_for
from tests.jobs_env import JobsEnv
from tests.test_records import _agent_ctx, bill

_ = world
B = "/api/v1"
IBAN = "GB82 WEST 1234 5698 7654 32"


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


async def _vendor(env: JobsEnv, name: str, **attributes: Any) -> Entity:
    agent = await _agent_ctx(env)
    async with env.uow.transaction() as s:
        return await entities.create_entity(
            s,
            agent,
            env.packs.packs["echo"].entity_type("echo_vendor"),
            pack_key="echo",
            name=name,
            attributes=attributes,
        )


async def test_a_job_creates_and_matches_vendors(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    @step
    async def _make(job: Job) -> str:
        eid = await job.effects.entities.create(
            "echo_vendor",
            "Northwind Traders",
            aliases=["NW Traders"],
            attributes={"tax_ids": ["GB 123 456"]},
        )
        return str(eid)

    async def run(job: Job) -> dict[str, Any]:
        made = await job.step("make", _make, job)
        by_tax = await job.entities.match("m1", "echo_vendor", "Someone", tax_id="gb123456")
        by_alias = await job.entities.match("m2", "echo_vendor", "nw traders")
        by_name = await job.entities.match("m3", "echo_vendor", "Northwind Trader")
        none = await job.entities.match("m4", "echo_vendor", "Contoso")
        return {
            "made": made,
            "tax": [str(by_tax.entity_id), by_tax.method],
            "alias": [str(by_alias.entity_id), by_alias.method],
            "name": [str(by_name.entity_id), by_name.method],
            "none": none.entity_id,
        }

    env = make_env()
    env.use("echo", run=run)
    await env.install("echo")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"], (await env.run(run_id)).error
    out = ((await env.run(run_id)).output or {})["result"]
    made = out["made"]
    assert out["tax"] == [made, "tax_id"]
    assert out["alias"] == [made, "alias"]
    assert out["name"] == [made, "similar"]  # trigram ≥ 0.6
    assert out["none"] is None


async def test_close_candidates_are_left_to_the_pack(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    await _vendor(env, "Acme Print Ltd")
    await _vendor(env, "Acme Prints Ltd")
    async with env.uow.transaction() as s:
        m = await entities.match(s, world.ravi.workspace_id, "echo_vendor", "Acme Print")
    assert m.entity_id is None and len(m.candidates) == 2  # too close to call: ask a person


async def test_bank_details_are_a_fingerprint_that_never_leaves_the_server(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    v = await _vendor(env, "Northwind")
    agent = await _agent_ctx(env)
    async with env.uow.transaction() as s:
        changed, last4 = await entities.set_bank(s, agent, v.id, IBAN)
        assert (changed, last4) == (False, "5432")  # the first one on file
        assert await entities.bank_matches(s, agent, v.id, IBAN.replace(" ", "").lower())
        assert not await entities.bank_matches(s, agent, v.id, "GB33BUKB20201555555555")
        changed, _ = await entities.set_bank(s, agent, v.id, "GB33BUKB20201555555555")
        assert changed is True  # a different account than the one on file
        row = await s.get(Entity, v.id, populate_existing=True)
        assert row is not None
        fp = row.attributes["bank"]["fingerprint"]
        assert len(fp) == 64 and IBAN.replace(" ", "") not in json.dumps(row.attributes)
        history = [
            a.diff
            for a in (await s.execute(select(Activity).where(Activity.entity_id == v.id))).scalars()
        ]
    assert fp not in json.dumps(history)
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        ravi = await clients("ravi")
        one = (await ravi.get(f"{B}/entities/{v.id}")).text
        many = (await ravi.get(f"{B}/entities", params={"type": "echo_vendor"})).text
        activity = (await ravi.get(f"{B}/activity", params={"entity_id": str(v.id)})).text
        await clients.close()
    for body in (one, many, activity):
        assert "fingerprint" not in body and fp not in body
    assert "•••• 5555" in one


async def test_merge_moves_records_and_skills_and_undoes_cleanly(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    keep = await _vendor(env, "Northwind")
    dupe = await _vendor(env, "North Wind Ltd")
    impl = env.packs.packs["echo"].record_type("echo_bill")
    agent = await _agent_ctx(env)
    project_id, task_id = world.project.id, world.copy.id
    async with env.uow.transaction() as s:
        r = await records.create_record(
            s,
            agent,
            impl,
            project_id=project_id,
            task_id=task_id,
            data=bill(vendor={"name": "North Wind Ltd", "entity_id": str(dupe.id)}),
        )
        sk = await skills.propose(
            s,
            agent,
            pack_key="echo",
            scope_type="entity",
            scope_id=dupe.id,
            kind="hint",
            content={"text": "The number is top right."},
        )
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden):
            await entities.merge(s, world.ana, dupe.id, keep.id)  # not an admin or steward
    async with env.uow.transaction() as s:
        merged = await entities.merge(s, admin, dupe.id, keep.id)
        assert {"North Wind Ltd"} <= set(merged.aliases)
        act = await s.scalar(select(Activity.id).where(Activity.verb == "entity.merged"))
    async with env.uow.transaction() as s:
        assert (await s.get(Record, r.id, populate_existing=True)).entity_ids == [keep.id]  # type: ignore[union-attr]
        assert (await s.get(Skill, sk.id, populate_existing=True)).scope_id == keep.id  # type: ignore[union-attr]
        assert (await s.get(Entity, dupe.id, populate_existing=True)).status == "merged"  # type: ignore[union-attr]
    async with env.uow.transaction() as s:
        await undo(s, admin, activity_id=act)
    async with env.uow.transaction() as s:
        assert (await s.get(Record, r.id, populate_existing=True)).entity_ids == [dupe.id]  # type: ignore[union-attr]
        assert (await s.get(Skill, sk.id, populate_existing=True)).scope_id == dupe.id  # type: ignore[union-attr]
        back = await s.get(Entity, dupe.id, populate_existing=True)
        survivor = await s.get(Entity, keep.id, populate_existing=True)
    assert back is not None and back.status == "active" and back.merged_into is None
    assert survivor is not None and "North Wind Ltd" not in survivor.aliases


async def test_stewards_may_merge_and_guests_see_nothing(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    from momentum.domain.pack_settings.service import put_values

    env = make_env()
    await env.install("echo")
    a = await _vendor(env, "Alpha")
    b = await _vendor(env, "Alpha Co")
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        await put_values(
            s,
            admin,
            env.packs.packs["echo"].settings,
            "echo",
            None,
            {"stewards": [str(world.ana.actor.id)]},
        )
    async with env.uow.transaction() as s:
        await entities.merge(s, world.ana, b.id, a.id)  # a steward may
        await s.execute(update(User).where(User.id == world.lena.actor.id).values(role="guest"))
    guest = await ctx_for(env.uow, env.settings, "lena")
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden):
            await entities.list_entities(s, guest)


async def test_nightly_profiles(make_env: Callable[..., JobsEnv], world: World) -> None:
    env = make_env()
    await env.install("echo")
    v = await _vendor(env, "Northwind")
    impl = env.packs.packs["echo"].record_type("echo_bill")
    agent = await _agent_ctx(env)
    project_id = world.project.id
    for total in ("100.00", "300.00", "200.00"):
        async with env.uow.transaction() as s:
            r = await records.create_record(
                s,
                agent,
                impl,
                project_id=project_id,
                data=bill(
                    number=total,
                    total=total,
                    lines=[],
                    vendor={"name": "Northwind", "entity_id": str(v.id)},
                ),
            )
        async with env.uow.transaction() as s:
            await records.update_record(
                s,
                world.ravi,
                impl,
                r.id,
                [SetStatusOp(op="set_status", status="approved")],
                expected_version=1,
            )
    async with env.uow.transaction() as s:
        assert await compute_profiles(s, env.packs) >= 1
    async with env.uow.transaction() as s:
        row = await s.get(Entity, v.id, populate_existing=True)
    assert row is not None and row.profile == {"records": 3, "median_total": "200.00"}
    _ = uuid
