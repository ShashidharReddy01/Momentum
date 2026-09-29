"""S5.3.2 Sorter · Triage: the new ``set_field_value`` tool (names and labels in, ids stored,
undoable), custom fields in ``get_task``, field changes recorded with an undo, and Sorter end to
end: a new top-level task gets proposals for the person who created it; subtasks are skipped."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from momentum.agents.loader import load_definitions
from momentum.ai.actions import apply_action, undo_action
from momentum.ai.models import AiAction
from momentum.core.activity import Activity
from momentum.core.undo import undo
from momentum.domain.agents.service import canonical
from momentum.domain.fields.models import FieldDef, FieldValue
from momentum.domain.fields.schemas import FieldCreateIn, SelectOptionIn
from momentum.domain.fields.service import create_field, set_task_field_value
from momentum.domain.notifications.models import Notification
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from tests.ai_fixtures import REG, world
from tests.test_agent_runtime import Env, make_env

_ = (make_env, world)
SORTER = next(d for d, _s in load_definitions() if d.key == "triage")


async def _risk_field(env: Env) -> FieldDef:
    async with env.uow.transaction() as s:
        m = await create_field(
            s,
            env.world.ravi,
            env.world.project.id,
            FieldCreateIn(
                name="Risk",
                type="single_select",
                options=[SelectOptionIn(label=x) for x in ("Low", "Medium", "High")],
            ),
        )
        return m.entity


def _option(field: FieldDef, label: str) -> str:
    return next(str(o["id"]) for o in field.options or [] if o["label"] == label)


async def _value(env: Env, task_id: Any, field_id: Any) -> Any:
    async with env.uow.transaction() as s:
        row = await s.get(FieldValue, (task_id, field_id))
        return row.value if row is not None else None


async def test_field_changes_are_recorded_and_undoable(make_env: Callable[..., Env]) -> None:
    env = make_env()
    risk = await _risk_field(env)
    copy = env.world.copy.id
    async with env.uow.transaction() as s:
        await set_task_field_value(s, env.world.ravi, copy, risk.id, _option(risk, "High"))
        # the same value again records nothing
        await set_task_field_value(s, env.world.ravi, copy, risk.id, _option(risk, "High"))
        acts = list(
            (
                await s.execute(
                    select(Activity).where(
                        Activity.entity_id == copy, Activity.verb == "task.field_set"
                    )
                )
            ).scalars()
        )
    assert len(acts) == 1 and acts[0].diff == {"field:Risk": [None, _option(risk, "High")]}
    async with env.uow.transaction() as s:
        await undo(s, env.world.ravi, activity_id=acts[0].id)
    assert await _value(env, copy, risk.id) is None


async def test_set_field_value_speaks_in_names_and_labels(make_env: Callable[..., Env]) -> None:
    env = make_env()
    risk = await _risk_field(env)
    task = {"title_query": "Draft pricing copy"}
    async with env.uow.transaction() as s:
        seen = await REG.invoke(s, env.world.ravi, "get_task", {"task": task}, mode="apply")
        fields = json.loads(json.dumps(seen.result.data))["task"]["custom_fields"]
        assert fields == [
            {"name": "Risk", "type": "single_select", "choices": ["Low", "Medium", "High"]}
        ]
        preview = await REG.invoke(
            s,
            env.world.ravi,
            "set_field_value",
            {"task": task, "field": "risk", "value": "high"},
            mode="dry_run",
        )
        assert preview.ok and preview.result.summary.startswith("Would set Risk = high")
        wrong = await REG.invoke(
            s,
            env.world.ravi,
            "set_field_value",
            {"task": task, "field": "Risk", "value": "Severe"},
            mode="dry_run",
        )
        assert not wrong.ok and "Low, Medium, High" in wrong.result.summary
        missing = await REG.invoke(
            s,
            env.world.ravi,
            "set_field_value",
            {"task": task, "field": "Effort", "value": 3},
            mode="dry_run",
        )
        assert not missing.ok and "fields: Risk" in missing.result.summary
    assert await _value(env, env.world.copy.id, risk.id) is None  # the preview wrote nothing
    async with env.uow.transaction() as s:
        done = await REG.invoke(
            s,
            env.world.ravi,
            "set_field_value",
            {"task": task, "field": "Risk", "value": "Medium"},
            mode="apply",
        )
        assert done.ok
        again = await REG.invoke(s, env.world.ravi, "get_task", {"task": task}, mode="apply")
    [shown] = json.loads(json.dumps(again.result.data))["task"]["custom_fields"]
    assert shown["value"] == "Medium"
    assert await _value(env, env.world.copy.id, risk.id) == _option(risk, "Medium")


async def test_sorter_proposes_triage_to_whoever_created_the_task(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    risk = await _risk_field(env)
    await env.install(SORTER)
    env.script(
        [
            {
                "match": {"contains": "Checkout crashes", "turn": 1},
                "tool_calls": [
                    {
                        "name": "update_task",
                        "arguments": {
                            "task": {"title_query": "Checkout crashes"},
                            "priority": "urgent",
                        },
                    },
                    {
                        "name": "set_field_value",
                        "arguments": {
                            "task": {"title_query": "Checkout crashes"},
                            "field": "Risk",
                            "value": "High",
                        },
                    },
                    {
                        "name": "add_comment",
                        "arguments": {
                            "task": {"title_query": "Checkout crashes"},
                            "text": "Possible duplicate of the pricing copy task: same page.",
                        },
                    },
                ],
            },
            {
                "match": {"contains": "Checkout crashes", "turn": 2},
                "text": "(mock) Urgent: it blocks checkout. Risk high. Possible duplicate noted.",
            },
        ],
        key="triage",
    )
    async with env.uow.transaction() as s:
        created = (
            await tasks.create_task(s, env.world.ana, env.world.project.id, "Checkout crashes")
        ).entity[0]
        # a subtask doesn't wake Sorter
        await tasks.create_subtask(s, env.world.ana, created.id, "Reproduce on Safari")
    assert await env.events() == 1
    assert await env.drain() == ["succeeded"]
    async with env.uow.transaction() as s:
        [action] = list(
            (await s.execute(select(AiAction).where(AiAction.source == "agent"))).scalars()
        )
        assert action.proposed_for == env.world.ana.actor.id
        assert [op["tool"] for op in action.operations] == [
            "update_task",
            "set_field_value",
            "add_comment",
        ]
        told = await s.scalar(
            select(Notification).where(
                Notification.user_id == env.world.ana.actor.id,
                Notification.kind == "agent_proposal",
            )
        )
        assert told is not None
    # nothing changed until ana applies it; then it all lands, and one undo takes it back
    assert await _value(env, created.id, risk.id) is None
    async with env.uow.transaction() as s:
        await apply_action(s, env.world.ana, REG, action.id)
    async with env.uow.transaction() as s:
        t = await s.get(Task, created.id)
        assert t is not None and t.priority == "urgent"
    assert await _value(env, created.id, risk.id) == _option(risk, "High")
    async with env.uow.transaction() as s:
        await undo_action(s, env.world.ana, action.id)
    assert await _value(env, created.id, risk.id) is None


def test_the_top_level_filter_hashes_as_before_when_unset() -> None:
    [trigger] = canonical(SORTER)["triggers"]
    assert trigger["filter"] == {"project_ids": None, "top_level": True}
    teammate = next(d for d, _s in load_definitions() if d.key == "teammate")
    assert all("filter" not in t for t in canonical(teammate)["triggers"])
