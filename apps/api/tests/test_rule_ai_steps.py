"""S4.1.5 AI step actions: the executor queues them instead of calling a model, the ``ai`` queue
runs them as the rule's author with the AI marking, the writes carry the rule's depth (loop
protection), a step that fails writes nothing, and a person's own field values are never
overwritten. Mock mode throughout (fixtures in ``evals/fixtures/mock_responses/ai_step_*.yaml``,
matched on the task's title)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from momentum.ai.llm import LLM, build_llm
from momentum.ai.rule_steps import claim_steps, run_step, step_ctx
from momentum.ai.tools.write_tools import text_doc
from momentum.core.db import UnitOfWork
from momentum.core.events import OutboxEvent
from momentum.core.settings import Settings
from momentum.domain.comments.models import Comment
from momentum.domain.comments.service import create_comment
from momentum.domain.fields.models import FieldDef, FieldValue
from momentum.domain.fields.schemas import FieldCreateIn, SelectOptionIn
from momentum.domain.fields.service import create_field, set_task_field_value
from momentum.domain.projects.service import delete_project
from momentum.domain.rules.engine import ACTIONS, MAX_DEPTH, run_rules
from momentum.domain.rules.models import RuleAiStep, RuleRun
from momentum.domain.rules.schemas import (
    ACTION_PARAMS,
    AI_STEP_KINDS,
    NOT_YET_ACTIONS,
    RuleIn,
)
from momentum.domain.rules.service import create_rule
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from momentum.domain.users.models import User
from tests.ai_fixtures import World, world
from tests.helpers import Clients

_ = world


@pytest.fixture
def llm(settings: Settings) -> LLM:
    return build_llm(settings)


# ---------------- helpers ----------------


async def _rule(uow: UnitOfWork, world: World, action: dict[str, Any], **extra: Any) -> uuid.UUID:
    async with uow.transaction() as s:
        rule = await create_rule(
            s,
            world.ravi,
            RuleIn.model_validate(
                {
                    "name": "AI step",
                    "project_id": str(world.project.id),
                    "trigger": {"type": "task.added"},
                    "actions": [action],
                    **extra,
                }
            ),
        )
        return rule.entity.id


async def _task(uow: UnitOfWork, world: World, title: str, **patch: Any) -> uuid.UUID:
    async with uow.transaction() as s:
        task = (await tasks.create_task(s, world.ravi, world.project.id, title)).entity[0]
        if patch:
            await tasks.update_task(s, world.ravi, task.id, patch)
        return task.id


async def _risk_field(uow: UnitOfWork, world: World) -> uuid.UUID:
    async with uow.transaction() as s:
        field = await create_field(
            s,
            world.ravi,
            world.project.id,
            FieldCreateIn(
                name="Risk",
                type="single_select",
                options=[SelectOptionIn(label=x) for x in ("Low", "Medium", "High")],
            ),
        )
        return field.entity.id


async def _run_rules(uow: UnitOfWork, settings: Settings) -> None:
    async with uow.transaction() as s:
        await run_rules(s, settings)


async def _steps(uow: UnitOfWork) -> list[RuleAiStep]:
    async with uow.transaction() as s:
        rows = await s.execute(select(RuleAiStep).order_by(RuleAiStep.created_at))
        return list(rows.scalars())


async def _work_the_queue(uow: UnitOfWork, llm: LLM, settings: Settings) -> list[str]:
    """One turn of the ``run_ai_steps`` job: claim in one transaction, run each in its own."""
    async with uow.transaction() as s:
        ids, _timed_out = await claim_steps(s)
    out = []
    for step_id in ids:
        async with uow.transaction() as s:
            out.append(await run_step(s, llm, settings, step_id))
    return out


async def _comments(uow: UnitOfWork, task_id: uuid.UUID) -> list[Comment]:
    async with uow.transaction() as s:
        rows = await s.execute(
            select(Comment).where(Comment.task_id == task_id).order_by(Comment.created_at)
        )
        return list(rows.scalars())


async def _values(uow: UnitOfWork, task_id: uuid.UUID) -> dict[uuid.UUID, Any]:
    async with uow.transaction() as s:
        rows = await s.execute(select(FieldValue).where(FieldValue.task_id == task_id))
        return {v.field_id: v.value for v in rows.scalars()}


# ---------------- the vocabulary ----------------


async def test_every_action_type_the_schema_offers_can_actually_run() -> None:
    """``ai_step`` is handled in ``_fire`` rather than through ``ACTIONS`` (it queues instead of
    writing), so the two together must cover exactly what the schema accepts."""
    runnable = set(ACTIONS) | {"ai_step"}
    assert runnable == set(ACTION_PARAMS) - NOT_YET_ACTIONS
    assert "slack_message" in NOT_YET_ACTIONS and "ai_step" not in NOT_YET_ACTIONS


async def test_the_api_validates_the_step_kind_and_its_field(
    as_user: Clients, world: World
) -> None:
    c = await as_user("ravi")
    base = {
        "name": "R",
        "project_id": str(world.project.id),
        "trigger": {"type": "task.added"},
    }

    async def post(action: dict[str, Any]) -> int:
        r = await c.post("/api/v1/rules", json={**base, "actions": [action]})
        return r.status_code

    assert await post({"type": "ai_step"}) == 422  # no kind
    assert await post({"type": "ai_step", "kind": "make_coffee"}) == 422
    assert await post({"type": "ai_step", "kind": "classify_field"}) == 422  # needs a field
    assert await post({"type": "ai_step", "kind": "classify_field", "field_id": "due_on"}) == 422
    assert await post({"type": "ai_step", "kind": "draft_reply", "field_id": "priority"}) == 422
    assert await post({"type": "ai_step", "kind": "summarize_to_comment"}) == 201
    assert await post({"type": "ai_step", "kind": "classify_field", "field_id": "priority"}) == 201
    assert await post({"type": "slack_message", "text": "hi"}) == 422  # still not available
    assert set(AI_STEP_KINDS) == {
        "summarize_to_comment",
        "classify_field",
        "extract_fields",
        "draft_reply",
    }


async def test_an_unknown_custom_field_in_a_step_is_refused(as_user: Clients, world: World) -> None:
    c = await as_user("ravi")
    r = await c.post(
        "/api/v1/rules",
        json={
            "name": "R",
            "project_id": str(world.project.id),
            "trigger": {"type": "task.added"},
            "actions": [
                {"type": "ai_step", "kind": "classify_field", "field_id": str(uuid.uuid4())}
            ],
        },
    )
    assert r.status_code == 422 and "field" in r.text


# ---------------- queue, not inline ----------------


async def test_the_executor_queues_the_step_instead_of_running_it(
    uow: UnitOfWork, settings: Settings, world: World
) -> None:
    rule_id = await _rule(
        uow, world, {"type": "ai_step", "kind": "classify_field", "field_id": "priority"}
    )
    task_id = await _task(uow, world, "QA the checkout flow")
    await _run_rules(uow, settings)

    async with uow.transaction() as s:
        run = (await s.execute(select(RuleRun).where(RuleRun.rule_id == rule_id))).scalar_one()
        assert (run.status, run.actions_run) == ("success", 1)
    (step,) = await _steps(uow)
    assert (step.status, step.kind, step.task_id, step.rule_run_id) == (
        "queued",
        "classify_field",
        task_id,
        run.id,
    )
    async with uow.transaction() as s:
        task = await s.get(Task, task_id)
        assert task is not None and task.priority is None  # nothing written yet


async def test_the_queue_sets_the_field_as_the_rules_author(
    uow: UnitOfWork, settings: Settings, world: World, llm: LLM
) -> None:
    await _rule(uow, world, {"type": "ai_step", "kind": "classify_field", "field_id": "priority"})
    task_id = await _task(uow, world, "QA the checkout flow")
    await _run_rules(uow, settings)

    assert await _work_the_queue(uow, llm, settings) == ["done"]
    async with uow.transaction() as s:
        task = await s.get(Task, task_id)
        assert task is not None and task.priority == "high"
    (step,) = await _steps(uow)
    assert step.status == "done" and step.result is not None and "high" in step.result
    assert step.finished_at is not None


async def test_a_summary_comment_is_marked_as_ai(
    uow: UnitOfWork, settings: Settings, world: World, llm: LLM
) -> None:
    task_id = await _task(uow, world, "Pricing tiers thread")
    async with uow.transaction() as s:
        await create_comment(s, world.ravi, task_id, text_doc("Three pricing tiers, I think."))
    await _rule(
        uow,
        world,
        {"type": "ai_step", "kind": "summarize_to_comment"},
        trigger={"type": "task.completed"},
    )
    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, task_id, True)
    await _run_rules(uow, settings)
    assert await _work_the_queue(uow, llm, settings) == ["done"]

    comments = await _comments(uow, task_id)
    assert len(comments) == 2
    ai = comments[-1]
    assert ai.is_ai is True and ai.created_via == "ai" and ai.author_id == world.ravi.actor.id


async def test_a_drafted_reply_that_comes_back_empty_fails_and_writes_nothing(
    uow: UnitOfWork, settings: Settings, world: World, llm: LLM
) -> None:
    await _rule(uow, world, {"type": "ai_step", "kind": "draft_reply"})
    task_id = await _task(uow, world, "Empty reply please")
    await _run_rules(uow, settings)

    assert await _work_the_queue(uow, llm, settings) == ["failed"]
    assert await _comments(uow, task_id) == []
    (step,) = await _steps(uow)
    assert step.status == "failed" and step.error and "empty" in step.error.lower()


# ---------------- classify / extract behaviour ----------------


async def test_a_value_that_isnt_one_of_the_fields_choices_is_refused(
    uow: UnitOfWork, settings: Settings, world: World, llm: LLM
) -> None:
    field_id = await _risk_field(uow, world)
    await _rule(
        uow, world, {"type": "ai_step", "kind": "classify_field", "field_id": str(field_id)}
    )
    task_id = await _task(uow, world, "Unknown option please")
    await _run_rules(uow, settings)

    assert await _work_the_queue(uow, llm, settings) == ["failed"]
    assert await _values(uow, task_id) == {}
    (step,) = await _steps(uow)
    assert step.error is not None and "choices" in step.error


async def test_a_step_that_finds_nothing_to_say_writes_nothing_and_still_succeeds(
    uow: UnitOfWork, settings: Settings, world: World, llm: LLM
) -> None:
    await _rule(uow, world, {"type": "ai_step", "kind": "classify_field", "field_id": "priority"})
    task_id = await _task(uow, world, "Nothing to say please")
    await _run_rules(uow, settings)

    assert await _work_the_queue(uow, llm, settings) == ["done"]
    async with uow.transaction() as s:
        task = await s.get(Task, task_id)
        assert task is not None and task.priority is None
    (step,) = await _steps(uow)
    assert step.result is not None and "No value" in step.result


async def test_extract_fields_never_overwrites_a_value_a_person_set(
    uow: UnitOfWork, settings: Settings, world: World, llm: LLM
) -> None:
    field_id = await _risk_field(uow, world)
    async with uow.transaction() as s:
        vendor_id = (
            await create_field(
                s, world.ravi, world.project.id, FieldCreateIn(name="Vendor", type="text")
            )
        ).entity.id
    task_id = await _task(uow, world, "Sign vendor contract")
    async with uow.transaction() as s:
        option = (await s.get(FieldDef, field_id)).options[0]["id"]  # type: ignore[union-attr,index]
        await set_task_field_value(s, world.ravi, task_id, field_id, option)
    await _rule(
        uow,
        world,
        {"type": "ai_step", "kind": "extract_fields"},
        trigger={"type": "task.completed"},
    )
    async with uow.transaction() as s:
        await tasks.set_completed(s, world.ravi, task_id, True)
    await _run_rules(uow, settings)

    assert await _work_the_queue(uow, llm, settings) == ["done"]
    # The fixture offers Vendor = DataCo and Risk = High. Risk already had "Low" from a person,
    # so it was never even offered to the model and keeps that value; only Vendor is filled in.
    assert await _values(uow, task_id) == {field_id: option, vendor_id: "DataCo"}


# ---------------- loop protection, claiming, history ----------------


async def test_the_steps_writes_carry_the_rules_depth(
    uow: UnitOfWork, settings: Settings, world: World, llm: LLM
) -> None:
    await _rule(uow, world, {"type": "ai_step", "kind": "classify_field", "field_id": "priority"})
    task_id = await _task(uow, world, "QA the checkout flow")
    await _run_rules(uow, settings)
    (step,) = await _steps(uow)
    assert step.depth == 1  # the rule fired on a person's change (depth 0), its writes are 1
    assert await _work_the_queue(uow, llm, settings) == ["done"]

    async with uow.transaction() as s:
        events = list(
            (
                await s.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.entity_id == task_id, OutboxEvent.type == "task.updated")
                    .order_by(OutboxEvent.id)
                )
            ).scalars()
        )
    assert events and int((events[-1].payload or {}).get("depth", 0)) == step.depth
    assert step.depth < MAX_DEPTH  # so a chain of AI steps still stops


async def test_a_claimed_step_isnt_claimed_twice(
    uow: UnitOfWork, settings: Settings, world: World
) -> None:
    await _rule(uow, world, {"type": "ai_step", "kind": "classify_field", "field_id": "priority"})
    await _task(uow, world, "QA the checkout flow")
    await _run_rules(uow, settings)

    async with uow.transaction() as s:
        first, _ = await claim_steps(s)
    async with uow.transaction() as s:
        second, _ = await claim_steps(s)
    assert len(first) == 1 and second == []


async def test_a_step_left_running_by_a_crashed_worker_times_out(
    uow: UnitOfWork, settings: Settings, world: World
) -> None:
    await _rule(uow, world, {"type": "ai_step", "kind": "classify_field", "field_id": "priority"})
    await _task(uow, world, "QA the checkout flow")
    await _run_rules(uow, settings)
    async with uow.transaction() as s:
        ids, _ = await claim_steps(s)
        await s.execute(
            update(RuleAiStep)
            .where(RuleAiStep.id.in_(ids))
            .values(started_at=datetime.now(UTC) - timedelta(hours=2))
        )
    async with uow.transaction() as s:
        again, timed_out = await claim_steps(s)
    assert again == [] and timed_out == 1
    (step,) = await _steps(uow)
    assert step.status == "failed" and step.error is not None and "in time" in step.error


async def test_the_step_is_refused_when_the_rules_author_is_gone(
    uow: UnitOfWork, settings: Settings, world: World, llm: LLM
) -> None:
    await _rule(uow, world, {"type": "ai_step", "kind": "classify_field", "field_id": "priority"})
    await _task(uow, world, "QA the checkout flow")
    await _run_rules(uow, settings)
    async with uow.transaction() as s:
        await s.execute(
            update(User).where(User.id == world.ravi.actor.id).values(status="disabled")
        )
    assert await _work_the_queue(uow, llm, settings) == ["failed"]
    (step,) = await _steps(uow)
    assert step.error is not None and "no longer active" in step.error


async def test_the_run_history_shows_each_steps_own_status(
    as_user: Clients, uow: UnitOfWork, settings: Settings, world: World, llm: LLM
) -> None:
    rule_id = await _rule(
        uow, world, {"type": "ai_step", "kind": "classify_field", "field_id": "priority"}
    )
    await _task(uow, world, "QA the checkout flow")
    await _run_rules(uow, settings)
    c = await as_user("ravi")

    queued = (await c.get(f"/api/v1/rules/{rule_id}/runs")).json()["data"]
    assert [s["status"] for s in queued[0]["ai_steps"]] == ["queued"]

    await _work_the_queue(uow, llm, settings)
    done = (await c.get(f"/api/v1/rules/{rule_id}/runs")).json()["data"]
    (one,) = done[0]["ai_steps"]
    assert one["status"] == "done" and one["kind"] == "classify_field"
    assert one["field_id"] == "priority" and one["result"]


async def test_a_test_run_reports_the_step_without_calling_a_model(
    as_user: Clients, uow: UnitOfWork, world: World
) -> None:
    rule_id = await _rule(uow, world, {"type": "ai_step", "kind": "summarize_to_comment"})
    task_id = await _task(uow, world, "Prepare press kit")
    c = await as_user("ravi")

    r = await c.post(f"/api/v1/rules/{rule_id}/test-run", json={"task_id": str(task_id)})
    assert r.status_code == 200, r.text
    assert r.json()["actions"] == [
        {"type": "ai_step: summarize_to_comment", "ok": True, "error": None}
    ]
    assert await _steps(uow) == []  # a preview queues nothing
    assert await _comments(uow, task_id) == []


async def test_a_failed_run_queues_no_step(
    uow: UnitOfWork, settings: Settings, world: World
) -> None:
    """The step row is written inside the run's savepoint, so a later action's failure takes it
    with it (here: the target project is deleted after the rule was saved)."""
    async with uow.transaction() as s:
        rule = await create_rule(
            s,
            world.ravi,
            RuleIn.model_validate(
                {
                    "name": "AI then a broken move",
                    "project_id": str(world.project.id),
                    "trigger": {"type": "task.added"},
                    "actions": [
                        {"type": "ai_step", "kind": "summarize_to_comment"},
                        {"type": "add_to_project", "project_id": str(world.other.id)},
                    ],
                }
            ),
        )
        rule_id = rule.entity.id
    async with uow.transaction() as s:
        await delete_project(s, world.ravi, world.other.id)
    await _task(uow, world, "QA the checkout flow")
    await _run_rules(uow, settings)

    async with uow.transaction() as s:
        run = (await s.execute(select(RuleRun).where(RuleRun.rule_id == rule_id))).scalar_one()
        assert run.status == "failed" and run.actions_run == 0
    assert await _steps(uow) == []


async def test_the_step_context_is_the_author_as_ai(
    uow: UnitOfWork, settings: Settings, world: World
) -> None:
    async with uow.transaction() as s:
        user = await s.get(User, world.ravi.actor.id)
        assert user is not None
        step = RuleAiStep(
            workspace_id=user.workspace_id,
            rule_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            kind="draft_reply",
            status="queued",
            depth=2,
        )
        ctx = step_ctx(user, settings, step)
    assert ctx.via == "ai" and ctx.actor.id == user.id and ctx.rule_depth == 2
    assert ctx.actor.timezone == user.timezone
