"""S3.1.3 AI actions: propose (preview only) → apply / reject / expire → undo, the stale check
that re-previews instead of applying blind, high-risk confirmation, all-or-nothing apply."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from momentum.ai.actions import (
    ProposedCall,
    apply_action,
    expire_actions,
    get_action,
    propose,
    reject_action,
    undo_action,
)
from momentum.ai.models import AiAction
from momentum.core.activity import Activity
from momentum.core.context import Ctx
from momentum.core.db import UnitOfWork
from momentum.core.errors import Conflict, NotFound, ValidationFailed
from momentum.domain.projects.service import delete_project
from momentum.domain.tasks import service as tasks
from tests.ai_fixtures import REG, World, key, state, task_row, world
from tests.helpers import Clients

_ = world


async def _propose(uow: UnitOfWork, ctx: Ctx, *calls: tuple[str, dict]) -> AiAction:  # type: ignore[type-arg]
    async with uow.transaction() as s:
        p = await propose(s, ctx, REG, [ProposedCall(t, a) for t, a in calls], source="command")
        assert p.action is not None, [(n, o.result.error) for n, o in p.failures]
        return p.action


async def _action(uow: UnitOfWork, action_id: uuid.UUID) -> AiAction:
    async with uow.transaction() as s:
        a = await s.get(AiAction, action_id)
        assert a is not None
        await s.refresh(a)
        return a


async def test_propose_previews_and_stores_without_changing_anything(
    uow: UnitOfWork, world: World
) -> None:
    before = await state(uow)
    action = await _propose(
        uow,
        world.ravi,
        ("update_task", {"task": key(world.copy), "due_on": "2026-10-09"}),
        ("add_comment", {"task": key(world.faq), "text": "On it"}),
    )
    after = await state(uow)
    assert after == before  # only the ai_actions row exists (not part of the domain snapshot)
    assert action.state == "proposed" and action.risk == "low" and action.source == "command"
    assert action.summary.startswith("2 changes: Would update")
    op0, op1 = action.operations
    assert op0["diff"][0]["changes"] == {"due_on": [None, "2026-10-09"]}
    assert op0["watch"] == [{"type": "task", "id": str(world.copy.id), "version": 1}]
    assert op1["watch"] == [{"type": "task", "id": str(world.faq.id), "version": 1}]
    assert action.expires_at - datetime.now(UTC) > timedelta(hours=23)


async def test_propose_reports_failures_and_refuses_read_tools(
    uow: UnitOfWork, world: World
) -> None:
    async with uow.transaction() as s:
        p = await propose(
            s,
            world.ravi,
            REG,
            [ProposedCall("complete_task", {"task": {"title_query": "draft pricing"}})],
            source="command",
        )
    assert p.action is None
    ((name, out),) = p.failures
    assert name == "complete_task" and out.result.error["code"] == "ambiguous"  # type: ignore[index]
    async with uow.transaction() as s:
        assert (await s.execute(select(AiAction))).first() is None
    with pytest.raises(ValidationFailed):
        async with uow.transaction() as s:
            await propose(
                s, world.ravi, REG, [ProposedCall("get_task", {"task": "T-1"})], source="chat"
            )


async def test_apply_runs_as_one_tagged_batch_and_undoes(uow: UnitOfWork, world: World) -> None:
    action = await _propose(
        uow,
        world.ravi,
        ("complete_task", {"task": key(world.copy)}),
        ("update_task", {"task": key(world.faq), "title": "Pricing FAQ"}),
    )
    async with uow.transaction() as s:
        r = await apply_action(s, world.ravi, REG, action.id)
    assert r.outcome == "applied" and r.action.state == "applied"
    batch = r.action.applied_batch_id
    async with uow.transaction() as s:
        rows = list((await s.execute(select(Activity).where(Activity.batch_id == batch))).scalars())
    assert {r.verb for r in rows} == {"task.completed", "task.updated"}
    assert all(r.ai_action_id == action.id for r in rows)
    assert (await task_row(uow, world.copy.id)).completed_at is not None

    async with uow.transaction() as s:
        undone = await undo_action(s, world.ravi, action.id)
    assert undone.state == "undone"
    assert (await task_row(uow, world.copy.id)).completed_at is None
    assert (await task_row(uow, world.faq.id)).title == "Draft pricing FAQ"
    with pytest.raises(Conflict):
        async with uow.transaction() as s:
            await undo_action(s, world.ravi, action.id)


async def test_stale_targets_are_repreviewed_not_applied(uow: UnitOfWork, world: World) -> None:
    """AC: someone changes the task after the preview → apply re-previews against the current
    data and asks again; the second apply goes through."""
    action = await _propose(
        uow, world.ravi, ("update_task", {"task": key(world.copy), "due_on": "2026-10-09"})
    )
    async with uow.transaction() as s:
        await tasks.update_task(s, world.ana, world.copy.id, {"title": "Pricing copy (final)"})
    async with uow.transaction() as s:
        r = await apply_action(s, world.ravi, REG, action.id)
    assert r.outcome == "repreviewed" and r.action.state == "proposed"
    op = r.action.operations[0]
    assert op["watch"][0]["version"] == 2
    assert op["diff"][0]["label"].endswith("Pricing copy (final)")
    t = await task_row(uow, world.copy.id)
    assert t.due_on is None  # not applied blind
    async with uow.transaction() as s:
        r = await apply_action(s, world.ravi, REG, action.id)
    assert r.outcome == "applied"
    assert (await task_row(uow, world.copy.id)).due_on is not None


async def test_stale_target_that_no_longer_works_fails_the_action(
    uow: UnitOfWork, world: World
) -> None:
    action = await _propose(uow, world.ravi, ("complete_task", {"task": key(world.copy)}))
    async with uow.transaction() as s:
        await tasks.delete_task(s, world.ana, world.copy.id)
    async with uow.transaction() as s:
        r = await apply_action(s, world.ravi, REG, action.id)
    assert r.outcome == "failed" and r.action.state == "failed"
    assert "complete_task" in (r.action.error or "")


async def test_high_risk_needs_confirmation(uow: UnitOfWork, world: World) -> None:
    """AC: applying a 30-item bulk requires the high-risk confirmation."""
    async with uow.transaction() as s:
        many = (
            await tasks.create_tasks(
                s, world.ravi, world.project.id, [f"Item {i}" for i in range(30)]
            )
        ).entity
    action = await _propose(
        uow,
        world.ravi,
        ("bulk_update_tasks", {"tasks": [key(t) for t, _ in many], "due_on": "2026-11-01"}),
    )
    assert action.risk == "high"
    aid, first_ids = action.id, [t.id for t, _ in many[:3]]
    with pytest.raises(Conflict) as err:
        async with uow.transaction() as s:
            await apply_action(s, world.ravi, REG, aid)
    assert err.value.code == "confirmation_required"
    assert (await _action(uow, aid)).state == "proposed"
    async with uow.transaction() as s:
        r = await apply_action(s, world.ravi, REG, aid, confirmed=True)
    assert r.outcome == "applied"
    for tid in first_ids:
        assert (await task_row(uow, tid)).due_on is not None


async def test_apply_is_all_or_nothing(uow: UnitOfWork, world: World) -> None:
    """The second operation fails at apply time (its project was deleted, which the version
    check doesn't see): the first one is rolled back too and the action is failed."""
    async with uow.transaction() as s:
        side = (await tasks.create_task(s, world.ravi, world.other.id, "Side task")).entity[0]
    action = await _propose(
        uow,
        world.ravi,
        ("complete_task", {"task": key(world.copy)}),
        ("complete_task", {"task": key(side)}),
    )
    async with uow.transaction() as s:
        await delete_project(s, world.ravi, world.other.id)
    before = await state(uow)
    async with uow.transaction() as s:
        r = await apply_action(s, world.ravi, REG, action.id)
    assert r.outcome == "failed" and r.action.state == "failed"
    assert r.action.error and "not_found" not in r.action.error  # a readable message
    assert (await task_row(uow, world.copy.id)).completed_at is None
    assert await state(uow) == before


async def test_reject_expire_and_ownership(uow: UnitOfWork, world: World) -> None:
    copy_key, copy_id = key(world.copy), world.copy.id  # objects expire when a Conflict rolls back
    a = await _propose(uow, world.ravi, ("complete_task", {"task": copy_key}))
    a_id = a.id
    async with uow.transaction() as s:
        assert (await reject_action(s, world.ravi, a_id)).state == "rejected"
    with pytest.raises(Conflict):
        async with uow.transaction() as s:
            await reject_action(s, world.ravi, a_id)
    with pytest.raises(Conflict):
        async with uow.transaction() as s:
            await apply_action(s, world.ravi, REG, a_id)

    b = await _propose(uow, world.ravi, ("complete_task", {"task": copy_key}))
    b_id = b.id
    with pytest.raises(NotFound):  # someone else's proposal
        async with uow.transaction() as s:
            await get_action(s, world.ana, b_id)
    async with uow.transaction() as s:
        await s.execute(
            update(AiAction)
            .where(AiAction.id == b_id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    async with uow.transaction() as s:
        assert await expire_actions(s) == 1
    with pytest.raises(Conflict) as err:
        async with uow.transaction() as s:
            await apply_action(s, world.ravi, REG, b_id)
    assert err.value.code == "action_expired"
    assert (await task_row(uow, copy_id)).completed_at is None


async def test_api_get_apply_confirm_reject_undo(
    uow: UnitOfWork, world: World, as_user: Clients
) -> None:
    ravi = await as_user("ravi")
    ana = await as_user("ana")
    a = await _propose(uow, world.ravi, ("delete_task", {"task": key(world.faq)}))
    r = await ravi.get(f"/api/v1/ai/actions/{a.id}")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["risk"] == "high" and body["state"] == "proposed"
    assert body["operations"][0]["diff"][0]["verb"] == "task.deleted"
    assert (await ana.get(f"/api/v1/ai/actions/{a.id}")).status_code == 404

    r = await ravi.post(f"/api/v1/ai/actions/{a.id}/apply", json={})
    assert r.status_code == 409 and r.json()["code"] == "confirmation_required"
    r = await ravi.post(f"/api/v1/ai/actions/{a.id}/apply", json={"confirm_high_risk": True})
    assert r.status_code == 200 and r.json()["outcome"] == "applied"
    assert (await task_row(uow, world.faq.id)).deleted_at is not None
    r = await ravi.post(f"/api/v1/ai/actions/{a.id}/undo")
    assert r.status_code == 200 and r.json()["data"]["state"] == "undone"
    assert (await task_row(uow, world.faq.id)).deleted_at is None

    b = await _propose(uow, world.ravi, ("complete_task", {"task": key(world.copy)}))
    r = await ravi.post(f"/api/v1/ai/actions/{b.id}/reject")
    assert r.status_code == 200 and r.json()["data"]["state"] == "rejected"
    assert (await ravi.post(f"/api/v1/ai/actions/{b.id}/apply", json={})).status_code == 409
    assert (await ravi.get(f"/api/v1/ai/actions/{uuid.uuid4()}")).status_code == 404
