"""Phase 7.6 S76-04 (spec §6): records. Types registered at install; created by a job's declared
effect and validated on every write; corrected only through operations (with versions, undo and
409 on a stale version); identity and duplicates; visibility (guests never see financial records,
by any route); the query engine (money per currency, arrays, date buckets); the pages endpoint."""

from __future__ import annotations

import io
import uuid
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.app import create_app
from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden, NotFound, ValidationFailed, VersionConflict
from momentum.core.undo import undo
from momentum.domain.records import query as rq
from momentum.domain.records import service as records
from momentum.domain.records.models import Record, RecordType, RecordVersion
from momentum.domain.records.schemas import (
    AddItemOp,
    DistributeOp,
    LinkEntityOp,
    MoveItemOp,
    RemoveItemOp,
    SetOp,
    SetStatusOp,
)
from momentum.domain.users.models import User
from momentum.sdk import Job, step
from tests.ai_fixtures import World, world
from tests.helpers import Clients, ctx_for
from tests.jobs_env import JobsEnv

_ = world
B = "/api/v1"


def bill(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "vendor": {"name": "Acme Ltd"},
        "number": "INV-0041",
        "total": "100.00",
        "currency": "usd",
        "dated": "2026-09-15",
        "lines": [
            {"description": "Widgets", "amount": "60.00"},
            {"description": "Gadgets", "amount": "40.00"},
        ],
    }
    base.update(over)
    return base


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


async def _env(make_env: Callable[..., JobsEnv]) -> tuple[JobsEnv, Any]:
    env = make_env()
    await env.install("echo")  # also registers echo's record types
    return env, env.packs.packs["echo"].record_type("echo_bill")


async def _make(env: JobsEnv, world: World, impl: Any, **over: Any) -> Record:
    agent_ctx = await _agent_ctx(env)
    async with env.uow.transaction() as s:
        return await records.create_record(
            s,
            agent_ctx,
            impl,
            project_id=world.project.id,
            task_id=world.copy.id,
            data=bill(**over),
        )


async def _agent_ctx(env: JobsEnv) -> Any:
    from momentum.agents.triggers import agent_ctx

    async with env.uow.transaction() as s:
        account = await s.get(User, env.agent.user_id)
        assert account is not None
    return agent_ctx(env.agent, account, env.settings)


async def test_install_registers_the_types(make_env: Callable[..., JobsEnv]) -> None:
    env, _impl = await _env(make_env)
    async with env.uow.transaction() as s:
        row = await s.scalar(select(RecordType).where(RecordType.key == "echo_bill"))
    assert row is not None and row.pack_key == "echo" and row.classification == "financial"
    assert row.display["amount"] == "total" and row.display["occurred_on"] == "dated"
    assert row.schema["title"] == "EchoBill"


async def test_a_job_creates_a_record_through_its_declared_effect(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    @step
    async def _save(job: Job) -> str:
        rid = await job.effects.records.create("echo_bill", bill(), status="needs_review")
        return str(rid)

    async def run(job: Job) -> str:
        rid = await job.step("save", _save, job)
        dupes = await job.records.find_duplicates("dupes", "echo_bill", bill())
        return f"{rid}:{len(dupes)}"

    env = make_env()
    env.use("echo", run=run)
    await env.install("echo")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"], (await env.run(run_id)).error
    result = str(((await env.run(run_id)).output or {})["result"])
    rid, dupes = result.split(":")
    assert dupes == "1"  # the record it just made has that identity
    async with env.uow.transaction() as s:
        r = await s.get(Record, uuid.UUID(rid))
        assert r is not None
    assert r.run_id == run_id and r.created_via == "agent" and r.status == "needs_review"
    assert r.title == "Acme Ltd INV-0041" and r.identity_key == "acmeltd|inv41"
    assert (r.amount, r.currency, str(r.occurred_on)) == (Decimal("100.0000"), "USD", "2026-09-15")
    assert r.data["total"] == "100.00"  # money stays a string in JSON
    assert r.checks[0]["id"] == "lines_add_up" and r.checks[0]["passed"] is True


async def test_a_record_cant_be_saved_invalid(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env, impl = await _env(make_env)
    agent = await _agent_ctx(env)
    # read once: a refused write rolls back, which expires every loaded object
    project_id, task_id = world.project.id, world.copy.id
    no_number = {k: v for k, v in bill().items() if k != "number"}
    for bad in (bill(total="lots"), bill(colour="red"), no_number):
        async with env.uow.transaction() as s:
            with pytest.raises(ValidationFailed, match="isn't valid"):
                await records.create_record(
                    s, agent, impl, project_id=project_id, task_id=task_id, data=bad
                )
    async with env.uow.transaction() as s:
        r = await records.create_record(
            s, agent, impl, project_id=project_id, task_id=task_id, data=bill()
        )
    async with env.uow.transaction() as s:
        with pytest.raises(ValidationFailed):
            await records.update_record(
                s,
                agent,
                impl,
                r.id,
                [SetOp(op="set", path="total", value="x")],
                expected_version=1,
            )


async def test_correction_operations_versions_and_undo(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env, impl = await _env(make_env)
    r = await _make(env, world, impl)
    async with env.uow.transaction() as s:
        r = await records.update_record(
            s,
            world.ravi,
            impl,
            r.id,
            [
                SetOp(op="set", path="lines[1].amount", value="50.00"),
                AddItemOp(op="add_item", array="lines", item={"description": "Fee", "amount": "0"}),
                MoveItemOp(op="move_item", array="lines", from_=2, to=0),
                DistributeOp(op="distribute", array="lines", field="amount", total=Decimal("100")),
            ],
            expected_version=1,
            reason="Fixing the lines",
        )
    assert r.version == 2
    assert [x["amount"] for x in r.data["lines"]] == ["33.33", "33.33", "33.34"]  # remainder last
    assert r.data["lines"][0]["description"] == "Fee"
    assert r.provenance["lines[2].amount"]["method"] == "rule"
    assert r.checks[0]["passed"] is True
    async with env.uow.transaction() as s:
        with pytest.raises(VersionConflict):
            await records.update_record(
                s,
                world.ravi,
                impl,
                r.id,
                [RemoveItemOp(op="remove_item", array="lines", index=0)],
                expected_version=1,
            )
        v2 = await s.scalar(
            select(RecordVersion).where(RecordVersion.record_id == r.id, RecordVersion.version == 2)
        )
        assert v2 is not None and v2.via == "review" and v2.reason == "Fixing the lines"
        assert [o["op"] for o in v2.change["ops"]] == ["set", "add_item", "move_item", "distribute"]
        act = await s.scalar(
            select(Activity.id).where(Activity.entity_id == r.id, Activity.verb == "record.updated")
        )
    async with env.uow.transaction() as s:
        await undo(s, world.ravi, activity_id=act)
    async with env.uow.transaction() as s:
        back = await s.get(Record, r.id, populate_existing=True)
    assert back is not None and back.version == 3 and len(back.data["lines"]) == 2
    assert back.data["lines"][1]["amount"] == "40.00"


async def test_link_entity_and_status_rules(make_env: Callable[..., JobsEnv], world: World) -> None:
    env, impl = await _env(make_env)
    r = await _make(env, world, impl)
    vendor = uuid.uuid4()
    async with env.uow.transaction() as s:
        r = await records.update_record(
            s,
            world.ravi,
            impl,
            r.id,
            [LinkEntityOp(op="link_entity", role="vendor", entity_id=vendor)],
            expected_version=1,
        )
    assert r.entity_ids == [vendor] and r.data["vendor"]["name"] == "Acme Ltd"
    from momentum.domain.projects.service import add_member

    async with env.uow.transaction() as s:
        await add_member(s, world.ravi, world.project.id, world.ana.actor.id, "editor")
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden, match="project admin"):  # an editor can't approve
            await records.update_record(
                s,
                world.ana,
                impl,
                r.id,
                [SetStatusOp(op="set_status", status="approved")],
                expected_version=2,
            )
    async with env.uow.transaction() as s:
        r = await records.update_record(
            s,
            world.ravi,
            impl,
            r.id,
            [SetStatusOp(op="set_status", status="approved")],
            expected_version=2,
        )
    assert r.status == "approved"
    # a person can't approve a record they made by hand
    async with env.uow.transaction() as s:
        mine = await records.create_record(
            s, world.ravi, impl, project_id=world.project.id, data=bill(number="INV-7")
        )
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden, match="made yourself"):
            await records.update_record(
                s,
                world.ravi,
                impl,
                mine.id,
                [SetStatusOp(op="set_status", status="approved")],
                expected_version=1,
            )


async def test_identity_duplicates_and_similar(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env, impl = await _env(make_env)
    a = await _make(env, world, impl)
    b = await _make(env, world, impl, number="inv 41")  # same identity once normalised
    c = await _make(env, world, impl, number="INV-0042")
    assert a.identity_key == b.identity_key == "acmeltd|inv41"
    async with env.uow.transaction() as s:
        dupes = await records.find_duplicates(
            s, a.workspace_id, "echo_bill", a.identity_key, exclude=a.id
        )
        assert [d.id for d in dupes] == [b.id]
        similar = await records.find_similar(
            s, a.workspace_id, "echo_bill", c.identity_key, amount=Decimal("100"), exclude=c.id
        )
    assert {r.id for r, _ in similar} == {a.id, b.id}
    assert records.normalize_identity("INV-0041") == "inv41"
    assert records.normalize_identity("  Acme, Ltd. ") == "acmeltd"


async def test_visibility_and_guests_never_see_financial_records(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env, impl = await _env(make_env)
    r = await _make(env, world, impl)
    async with env.uow.transaction() as s:
        with pytest.raises(NotFound):
            await records.get_record(s, world.tom, r.id)  # can't see the project
        await records.get_record(s, world.lena, r.id)  # a viewer can
        await s.execute(update(User).where(User.id == world.lena.actor.id).values(role="guest"))
    guest = await ctx_for(env.uow, env.settings, "lena")
    async with env.uow.transaction() as s:
        with pytest.raises(NotFound):
            await records.get_record(s, guest, r.id)
        rows, total = await records.list_records(s, guest)
        assert rows == [] and total == 0
        out = await rq.run_query(s, guest, rq.RecordQuery(type="echo_bill"))
        assert out.rows == [] and out.notes == ["Guests can't see these records"]
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        lena = await clients("lena")
        assert (await lena.get(f"{B}/records")).json()["data"] == []
        assert (await lena.get(f"{B}/records/{r.id}")).status_code == 404
        q = await lena.post(f"{B}/records/query", json={"type": "echo_bill"})
        assert q.json()["rows"] == []
        ravi = await clients("ravi")
        listed = (await ravi.get(f"{B}/records", params={"type": "echo_bill"})).json()["data"]
        assert [x["id"] for x in listed] == [str(r.id)]
        assert listed[0]["classification"] == "financial"
        await clients.close()


async def test_the_query_engine(make_env: Callable[..., JobsEnv], world: World) -> None:
    env, impl = await _env(make_env)
    await _make(env, world, impl)
    await _make(env, world, impl, number="2", total="50.00", lines=[], dated="2026-10-02")
    await _make(env, world, impl, number="3", total="70.00", currency="EUR", lines=[])
    await _make(env, world, impl, vendor={"name": "Globex"}, number="4", total="10.00", lines=[])
    q = rq.RecordQuery(
        type="echo_bill",
        group_by=["vendor.name"],
        measures=[rq.MeasureSpec(op="sum", path="total"), rq.MeasureSpec(op="count")],
    )
    async with env.uow.transaction() as s:
        out = await rq.run_query(s, world.ravi, q)
    got = {(r.group["vendor.name"], r.currency): r.values for r in out.rows}
    # money never mixes currencies: Acme's USD and EUR are separate rows
    assert got[("Acme Ltd", "USD")] == {"sum(total)": 150.0, "count": 2.0}
    assert got[("Acme Ltd", "EUR")] == {"sum(total)": 70.0, "count": 1.0}
    assert got[("Globex", "USD")] == {"sum(total)": 10.0, "count": 1.0}
    assert any("per currency" in n for n in out.notes)
    async with env.uow.transaction() as s:
        months = await rq.run_query(
            s,
            world.ravi,
            rq.RecordQuery(
                type="echo_bill",
                group_by=["month:dated"],
                filters=[rq.Filter(path="currency", value="USD")],
                measures=[rq.MeasureSpec(op="sum", path="total")],
                order="group",
            ),
        )
        lines = await rq.run_query(
            s,
            world.ravi,
            rq.RecordQuery(
                type="echo_bill",
                array="lines",
                group_by=["lines[].description"],
                measures=[rq.MeasureSpec(op="sum", path="lines[].amount")],
                filters=[rq.Filter(path="currency", value="USD")],
            ),
        )
        big = await rq.run_query(
            s,
            world.ravi,
            rq.RecordQuery(type="echo_bill", filters=[rq.Filter(path="total", op="gte", value=60)]),
        )
    assert [(r.group["month:dated"], r.values["sum(total)"]) for r in months.rows] == [
        ("2026-09-01", 110.0),
        ("2026-10-01", 50.0),
    ]
    assert {
        r.group["lines[].description"]: r.values["sum(lines[].amount)"] for r in lines.rows
    } == {
        "Widgets": 60.0,
        "Gadgets": 40.0,
    }
    assert big.rows[0].values == {"count": 2.0}
    with pytest.raises(ValueError):
        rq.MeasureSpec(op="sum")


async def test_the_api_corrects_with_operations_and_refuses_a_stale_version(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env, impl = await _env(make_env)
    r = await _make(env, world, impl)
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        app.state.momentum.packs = env.packs  # the test packs, as the worker sees them
        clients = Clients(app)
        ravi = await clients("ravi")
        body = {"ops": [{"op": "set", "path": "number", "value": "INV-9"}], "expected_version": 1}
        ok = await ravi.patch(f"{B}/records/{r.id}", json=body)
        assert ok.status_code == 200, ok.text
        assert ok.json()["title"] == "Acme Ltd INV-9" and ok.json()["version"] == 2
        stale = await ravi.patch(f"{B}/records/{r.id}", json=body)
        assert stale.status_code == 409, stale.text
        detail = (await ravi.get(f"{B}/records/{r.id}")).json()
        assert [v["version"] for v in detail["versions"]] == [2, 1]
        lena = await clients("lena")  # a viewer can't correct
        r2 = await lena.patch(f"{B}/records/{r.id}", json={**body, "expected_version": 2})
        assert r2.status_code == 403, r2.text
        await clients.close()


async def test_the_pages_endpoint_renders_and_caches(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    from PIL import Image

    from momentum.agents.extensions import attach_file

    env, impl = await _env(make_env)
    png = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(png, "PNG")
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
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        ravi = await clients("ravi")
        page = await ravi.get(f"{B}/records/{r.id}/pages/1")
        assert page.status_code == 200 and page.headers["content-type"] == "image/jpeg"
        again = await ravi.get(f"{B}/records/{r.id}/pages/1")
        assert again.content == page.content
        assert (await ravi.get(f"{B}/records/{r.id}/pages/2")).status_code == 404
        await clients.close()
