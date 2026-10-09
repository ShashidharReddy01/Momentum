"""Phase 7.6 S76-05 (spec §7.2): skills. Proposed by a job (scrubbed: a hint carrying a record
value or an email is refused with its reason, kept redacted), tried out by the pack's child job,
decided by stewards and admins (approve, edit-and-approve, reject, retire, each undoable), used
most-specific-first and scored helped/hurt on approval, flagged when it may be hurting; starter
skills install as active; one daily digest per pack."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden, ValidationFailed
from momentum.core.undo import undo
from momentum.domain.notifications.models import Notification
from momentum.domain.records import service as records
from momentum.domain.records.schemas import SetOp, SetStatusOp
from momentum.domain.skills import service as skills
from momentum.domain.skills.models import Skill
from momentum.sdk import Job, step
from tests.ai_fixtures import World, world
from tests.helpers import ctx_for
from tests.jobs_env import JobsEnv
from tests.test_records import _agent_ctx, bill

_ = world


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


async def _skill(env: JobsEnv, skill_id: uuid.UUID) -> Skill:
    async with env.uow.transaction() as s:
        row = await s.get(Skill, skill_id, populate_existing=True)
        assert row is not None
        return row


async def test_a_job_proposes_a_skill_and_it_is_tried_out(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    record = bill(number="INV-20417")

    async def run(job: Job) -> list[dict[str, Any]]:
        good = await job.skills.propose(
            "good",
            "hint",
            {"text": "The invoice number is printed top right, under the logo."},
            field="number",
            record_values=record,
        )
        leaky = await job.skills.propose(
            "leaky",
            "hint",
            {"text": "The number is INV-20417, ask ap@acme-demo.test."},
            field="number",
            record_values=record,
        )
        return [good.model_dump(mode="json"), leaky.model_dump(mode="json")]

    env = make_env()
    env.use("echo", run=run)
    await env.install("echo")
    run_id = await env.start(task=world.copy)
    statuses = await env.drain()
    assert statuses.count("succeeded") == 2, ((await env.run(run_id)).error, statuses)
    good, leaky = ((await env.run(run_id)).output or {})["result"]
    assert good["status"] == "proposed"
    assert leaky["status"] == "rejected"
    assert "a value from the record" in leaky["note"] and "an email address" in leaky["note"]
    refused = await _skill(env, uuid.UUID(leaky["id"]))
    assert "INV-20417" not in refused.content["text"] and "ap@acme" not in refused.content["text"]
    tried = await _skill(env, uuid.UUID(good["id"]))
    # echo's tryout child job recorded its before/after
    assert tried.tryout is not None and tried.tryout["after"] == {"wrong": 0}
    assert tried.provenance["run_id"] == str(run_id)


async def test_deciding_skills(make_env: Callable[..., JobsEnv], world: World) -> None:
    env = make_env()
    await env.install("echo")
    agent = await _agent_ctx(env)
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        a = await skills.propose(
            s,
            agent,
            pack_key="echo",
            scope_type="workspace",
            scope_id=None,
            kind="hint",
            content={"text": "Totals are bold."},
        )
        b = await skills.propose(
            s,
            agent,
            pack_key="echo",
            scope_type="workspace",
            scope_id=None,
            kind="rule",
            content={"date_order": "MDY"},
        )
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden):
            await skills.decide(s, world.ana, a.id, "approve")  # not a steward or admin
    async with env.uow.transaction() as s:
        edited = await skills.decide(
            s, admin, a.id, "approve", content={"text": "Totals are bold, bottom right."}
        )
        await skills.decide(s, admin, b.id, "reject", note="We're DMY")
    assert edited.status == "active" and edited.version == 2 and edited.supersedes_id == a.id
    assert (await _skill(env, a.id)).status == "retired"
    assert (await _skill(env, b.id)).status == "rejected"
    async with env.uow.transaction() as s:
        rej = await s.scalar(
            select(Activity.id).where(Activity.entity_id == b.id, Activity.verb == "skill.rejected")
        )
    async with env.uow.transaction() as s:
        await undo(s, admin, activity_id=rej)
    assert (await _skill(env, b.id)).status == "proposed"
    async with env.uow.transaction() as s:
        with pytest.raises(ValidationFailed, match="email"):
            await skills.author(
                s,
                admin,
                pack_key="echo",
                scope_type="workspace",
                scope_id=None,
                kind="hint",
                content={"text": "Write to billing@northwind.test"},
            )
        written = await skills.author(
            s,
            admin,
            pack_key="echo",
            scope_type="workspace",
            scope_id=None,
            kind="hint",
            content={"text": "Dates are day first."},
        )
    assert written.status == "active" and written.source == "authored"


async def test_starter_skills_install_once_as_active(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    await env.install("echo", access=False)  # again: nothing doubles
    async with env.uow.transaction() as s:
        starters = list((await s.execute(select(Skill).where(Skill.source == "starter"))).scalars())
    assert sorted(x.starter_key or "" for x in starters) == ["date_order", "tax_row_is_not_a_line"]
    assert {x.status for x in starters} == {"active"}


async def test_use_order_and_scoring(make_env: Callable[..., JobsEnv], world: World) -> None:
    env = make_env()
    await env.install("echo")
    agent = await _agent_ctx(env)
    admin = await ctx_for(env.uow, env.settings, "admin")
    vendor = uuid.uuid4()
    async with env.uow.transaction() as s:
        proj = await skills.author(
            s,
            admin,
            pack_key="echo",
            scope_type="project",
            scope_id=world.project.id,
            kind="hint",
            content={"text": "This project's bills are scanned."},
        )
        ent = await skills.author(
            s,
            admin,
            pack_key="echo",
            scope_type="entity",
            scope_id=vendor,
            kind="hint",
            field="number",
            content={"text": "The number is under the logo."},
        )
    async with env.uow.transaction() as s:
        used = await skills.active_for(
            s, admin.workspace_id, "echo", entity_id=vendor, project_id=world.project.id
        )
    assert [u.scope_type for u in used][:2] == ["entity", "project"]
    assert {u.id for u in used} >= {proj.id, ent.id}
    # a record that used the entity skill for "number": approved untouched → helped
    impl = env.packs.packs["echo"].record_type("echo_bill")
    project_id = world.project.id
    async with env.uow.transaction() as s:
        r = await records.create_record(
            s,
            agent,
            impl,
            project_id=project_id,
            data=bill(),
            provenance={"skills_used": {str(ent.id): ["number"]}},
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
    assert (await _skill(env, ent.id)).metrics["helped"] == 1
    # another that was corrected on that field → hurt
    async with env.uow.transaction() as s:
        r2 = await records.create_record(
            s,
            agent,
            impl,
            project_id=project_id,
            data=bill(number="9"),
            provenance={"skills_used": {str(ent.id): ["number"]}},
        )
    async with env.uow.transaction() as s:
        await records.update_record(
            s,
            world.ravi,
            impl,
            r2.id,
            [SetOp(op="set", path="number", value="INV-9")],
            expected_version=1,
        )
        await records.update_record(
            s,
            world.ravi,
            impl,
            r2.id,
            [SetStatusOp(op="set_status", status="approved")],
            expected_version=2,
        )
    m = (await _skill(env, ent.id)).metrics
    assert (m["helped"], m["hurt"]) == (1, 1)


async def test_may_be_hurting_after_five_uses(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("echo")
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        sk = await skills.author(
            s,
            admin,
            pack_key="echo",
            scope_type="workspace",
            scope_id=None,
            kind="hint",
            content={"text": "Totals are at the bottom."},
        )
    async with env.uow.transaction() as s:
        row = await s.get(Skill, sk.id)
        assert row is not None
        row.metrics = {"uses": 5, "helped": 1, "hurt": 3}
    row = await _skill(env, sk.id)
    assert skills.may_be_hurting(row) and row.status == "active"  # flagged, never retired


async def test_the_daily_digest_goes_to_stewards(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    from momentum.domain.pack_settings.service import put_values

    env = make_env()
    await env.install("echo")
    agent = await _agent_ctx(env)
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
        for text in ("Totals are bold.", "Dates are under the logo."):
            await skills.propose(
                s,
                agent,
                pack_key="echo",
                scope_type="workspace",
                scope_id=None,
                kind="hint",
                content={"text": text},
            )
    async with env.uow.transaction() as s:
        assert await skills.digest(s, env.settings, datetime.now(UTC)) == 1
        notes = list(
            (
                await s.execute(select(Notification).where(Notification.kind == "skill_proposed"))
            ).scalars()
        )
    assert [n.user_id for n in notes] == [world.ana.actor.id]
    assert notes[0].title == "2 skill(s) from echo to review"


async def test_example_skills_are_scrubbed_too(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    @step
    async def _p(job: Job) -> dict[str, Any]:
        out = await job.effects.skills.propose(
            "rule", {"vendor_phone": "+44 20 7946 0958"}, record_values=None
        )
        return out.model_dump(mode="json")

    async def run(job: Job) -> dict[str, Any]:
        return await job.step("p", _p, job)

    env = make_env()
    env.use("echo", run=run)
    await env.install("echo")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    out = ((await env.run(run_id)).output or {})["result"]
    assert out["status"] == "rejected" and "a phone number" in out["note"]
