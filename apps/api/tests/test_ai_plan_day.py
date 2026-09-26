"""S3.4.5 plan my day: a previewed change to My Tasks (nothing moves until applied), applied
through move_my_task with one undo, the model's keys checked (only my open tasks, no duplicates,
Today capped), the plan_my_day tool's own guards, and "already planned" proposing nothing."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from momentum.ai.actions import apply_action
from momentum.ai.llm import build_llm
from momentum.ai.plan_day import CAPACITY, PlanResult, plan_day
from momentum.core.context import Ctx
from momentum.core.db import UnitOfWork
from momentum.core.errors import ValidationFailed
from momentum.domain.mytasks.models import MyTaskPlacement
from momentum.domain.mytasks.service import list_my_tasks
from momentum.domain.tasks import service as tasks
from tests.ai_fixtures import REG, World, call, key, undo_batch, world
from tests.conftest import make_settings
from tests.helpers import Clients

_ = world
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
async def _no_seeded_assignments(uow: UnitOfWork, world: World) -> None:
    """The seed assigns tasks at random; these tests plan only their own (journey-scoped)."""
    from sqlalchemy import update

    from momentum.domain.tasks.models import Task

    async with uow.transaction() as s:
        await s.execute(update(Task).values(assignee_id=None))


async def plan(uow: UnitOfWork, ctx: Ctx) -> PlanResult:
    llm = build_llm(make_settings())
    async with uow.transaction() as s:
        return await plan_day(s, llm, ctx.with_(via="ai"), REG, now=NOW)


async def buckets(uow: UnitOfWork, ctx: Ctx) -> dict[str, list[str]]:
    async with uow.transaction() as s:
        rows = await list_my_tasks(s, ctx)
        out: dict[str, list[str]] = {}
        for t, p in rows:
            out.setdefault(p.bucket if p else "?", []).append(t.title)
        return out


async def assign_to_ravi(uow: UnitOfWork, world: World, *task_ids: uuid.UUID) -> None:
    async with uow.transaction() as s:
        for tid in task_ids:
            await tasks.update_task(s, world.ravi, tid, {"assignee_id": world.ravi.actor.id})


async def test_plan_previews_then_applies_then_undoes(uow: UnitOfWork, world: World) -> None:
    await assign_to_ravi(uow, world, world.copy.id, world.faq.id)
    before = await buckets(uow, world.ravi)
    assert set(before) == {"recently_assigned"}
    assert sorted(before["recently_assigned"]) == ["Draft pricing FAQ", "Draft pricing copy"]
    r = await plan(uow, world.ravi)
    assert r.action_id is not None and set(r.today) == {key(world.copy), key(world.faq)}
    assert r.rationale.startswith("(mock) Plan for")
    assert await buckets(uow, world.ravi) == before  # a preview only
    async with uow.transaction() as s:
        applied = await apply_action(s, world.ravi, REG, r.action_id)
        (op,) = applied.action.operations
        assert op["tool"] == "plan_my_day"
        labels = {d["label"] for d in op["diff"]}
        assert labels == {
            f"{key(world.copy)} Draft pricing copy",
            f"{key(world.faq)} Draft pricing FAQ",
        }
    after = await buckets(uow, world.ravi)
    by_key = {key(world.copy): "Draft pricing copy", key(world.faq): "Draft pricing FAQ"}
    assert after == {"today": [by_key[k] for k in r.today]}  # in the planned order
    async with uow.transaction() as s:
        pinned = (await s.execute(select(MyTaskPlacement.pinned))).scalars().all()
        assert all(pinned)  # the daily pass leaves hand-planned tasks alone
    # the same plan again: nothing to change, nothing proposed
    again = await plan(uow, world.ravi)
    assert again.action_id is None
    await undo_batch(uow, world.ravi, applied.action.applied_batch_id)
    assert await buckets(uow, world.ravi) == before


async def test_keys_are_checked_and_today_is_capped(uow: UnitOfWork, world: World) -> None:
    ids = []
    async with uow.transaction() as s:
        for i in range(CAPACITY + 1):
            ids.append(
                (await tasks.create_task(s, world.ravi, world.project.id, f"Item {i}")).entity[0].id
            )
        ids.append(
            (await tasks.create_task(s, world.ravi, world.project.id, "Test plan with outsiders"))
            .entity[0]
            .id
        )
    await assign_to_ravi(uow, world, *ids)
    r = await plan(uow, world.ravi)
    assert len(r.today) == CAPACITY
    notes = "\n".join(r.notes)
    assert "Left out T-999999: it isn't one of your open tasks." in notes
    assert f"Kept the first {CAPACITY} for today" in notes


async def test_nothing_to_plan(uow: UnitOfWork, world: World) -> None:
    with pytest.raises(ValidationFailed):
        await plan(uow, world.ana)  # ana has no open tasks


async def test_tool_guards(uow: UnitOfWork, world: World) -> None:
    await assign_to_ravi(uow, world, world.copy.id)
    async with uow.transaction() as s:
        await tasks.update_task(s, world.ravi, world.faq.id, {"assignee_id": world.ana.actor.id})
    not_mine = await call(uow, world.ravi, "plan_my_day", {"today": [key(world.faq)]})
    assert not not_mine.ok and not_mine.result.error["code"] == "not_found"  # type: ignore[index]
    twice = await call(
        uow, world.ravi, "plan_my_day", {"today": [key(world.copy)], "later": [key(world.copy)]}
    )
    assert not twice.ok and "listed twice" in twice.result.error["message"]  # type: ignore[index]
    empty = await call(uow, world.ravi, "plan_my_day", {})
    assert not empty.ok
    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, world.copy.id, True)
    done = await call(uow, world.ravi, "plan_my_day", {"today": [key(world.copy)]})
    assert not done.ok


async def test_endpoint(as_user: Clients, uow: UnitOfWork, world: World) -> None:
    await assign_to_ravi(uow, world, world.copy.id, world.faq.id)
    async with uow.transaction() as s:  # overdue: the daily pass already put it in Today
        await tasks.update_task(s, world.ravi, world.copy.id, {"due_on": date(2020, 1, 1)})
    ravi = await as_user("ravi")
    r = await ravi.post("/api/v1/ai/plan-my-day")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["today"]) == {key(world.copy), key(world.faq)} and body["action_id"]
    assert any(c["valid"] and c["key"] == key(world.copy) for c in body["citations"])
    ana = await as_user("ana")
    assert (await ana.post("/api/v1/ai/plan-my-day")).status_code == 422


async def test_already_planned_proposes_nothing(uow: UnitOfWork, world: World) -> None:
    await assign_to_ravi(uow, world, world.copy.id)
    async with uow.transaction() as s:
        await tasks.update_task(s, world.ravi, world.copy.id, {"due_on": date(2020, 1, 1)})
    r = await plan(uow, world.ravi)
    assert r.action_id is None and r.today == [key(world.copy)]


async def test_the_plan_goes_first_in_today(uow: UnitOfWork, world: World) -> None:
    await assign_to_ravi(uow, world, world.copy.id, world.faq.id)
    async with uow.transaction() as s:  # FAQ is already in Today (overdue)
        await tasks.update_task(s, world.ravi, world.faq.id, {"due_on": date(2020, 1, 1)})
    out = await call(uow, world.ravi, "plan_my_day", {"today": [key(world.copy)]}, mode="apply")
    assert out.ok
    assert (await buckets(uow, world.ravi))["today"] == ["Draft pricing copy", "Draft pricing FAQ"]
