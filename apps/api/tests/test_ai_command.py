"""S3.2.2 ⌘K natural-language commands: the tool loop (mock multi-step fixtures), proposals
becoming one AI action, clarification instead of guessing, auto-apply of low-risk changes, the
SSE endpoint, and the mock transport's turn/$last support."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from momentum.ai.command import run_command
from momentum.ai.context import Screen
from momentum.ai.llm import LLM, build_llm
from momentum.ai.loop import OUT_OF_STEPS
from momentum.ai.mock import _fill, _turn
from momentum.ai.models import AiAction
from momentum.ai.prefs import AiPrefs, set_prefs
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.tasks import service as tasks
from tests.ai_fixtures import REG, World, key, task_row, world
from tests.conftest import make_settings
from tests.helpers import Clients, user_by_local

_ = world
NOW = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)


async def run(
    uow: UnitOfWork, world_ctx: Any, text: str, llm: LLM | None = None
) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(t: str, d: dict[str, Any]) -> None:
        events.append((t, d))

    async with uow.transaction() as s:
        await run_command(
            s,
            llm or build_llm(make_settings()),
            world_ctx.with_(via="ai"),
            REG,
            text,
            screen=Screen(kind="home"),
            now=NOW,
            emit=emit,
        )
    return events


def of(events: list[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [d for t, d in events if t == kind]


async def _overdue(uow: UnitOfWork, world: World) -> None:
    async with uow.transaction() as s:
        for t in (world.copy, world.faq):
            await tasks.update_task(s, world.ravi, t.id, {"due_on": date(2020, 1, 1)})


async def test_j7_shape_search_then_bulk_preview_then_apply(uow: UnitOfWork, world: World) -> None:
    await _overdue(uow, world)
    copy_id, faq_id = world.copy.id, world.faq.id
    events = await run(uow, world.ravi, "Assign all overdue tasks in AI Tools Lab to Ana")
    kinds = [t for t, _ in events]
    assert kinds == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "token",
        "action_proposed",
        "done",
    ]
    results = of(events, "tool_result")
    assert results[0]["name"] == "search_tasks" and results[0]["preview"] is False
    assert results[1]["name"] == "bulk_update_tasks" and results[1]["preview"] is True
    (proposed,) = of(events, "action_proposed")
    assert proposed["risk"] == "medium"
    # nothing applied yet
    assert (await task_row(uow, copy_id)).assignee_id is None
    async with uow.transaction() as s:
        action = await s.get(AiAction, uuid.UUID(proposed["action_id"]))
        assert action is not None and action.source == "command" and action.state == "proposed"
        (op,) = action.operations
        assert op["tool"] == "bulk_update_tasks" and len(op["args"]["tasks"]) == 2
    ana = await user_by_local(uow, "ana")
    from momentum.ai.actions import apply_action

    async with uow.transaction() as s:
        r = await apply_action(s, world.ravi, REG, uuid.UUID(proposed["action_id"]))
    assert r.outcome == "applied"
    assert (await task_row(uow, copy_id)).assignee_id == ana.id
    assert (await task_row(uow, faq_id)).assignee_id == ana.id


async def test_ambiguous_target_asks_instead_of_guessing(uow: UnitOfWork, world: World) -> None:
    events = await run(uow, world.ravi, "Assign the pricing task to Ana")
    assert not of(events, "action_proposed")
    (clarify,) = of(events, "clarify")
    assert clarify["question"].startswith("Several tasks match")
    # ours plus the seeded Website Revamp "pricing" tasks ravi can also see
    assert {key(world.copy), key(world.faq)} <= {c["key"] for c in clarify["candidates"]}
    async with uow.transaction() as s:
        assert (await s.execute(select(AiAction))).first() is None


async def test_auto_apply_low_risk_only(uow: UnitOfWork, world: World) -> None:
    faq_id = world.faq.id
    async with uow.transaction() as s:
        await set_prefs(s, world.ravi, AiPrefs(auto_apply_low_risk=True))
    events = await run(uow, world.ravi, "Complete Draft pricing FAQ")
    (applied,) = of(events, "action_applied")
    assert applied["batch_id"]
    assert (await task_row(uow, faq_id)).completed_at is not None
    # high risk is never auto-applied
    events = await run(uow, world.ravi, "Delete Draft pricing FAQ")
    assert of(events, "action_proposed")[0]["risk"] == "high"
    assert not of(events, "action_applied")
    assert (await task_row(uow, faq_id)).deleted_at is None


async def test_permissions_still_apply_to_what_mo_proposes(uow: UnitOfWork, world: World) -> None:
    events = await run(uow, world.lena, "Complete Draft pricing FAQ")  # lena is a viewer
    assert of(events, "tool_result")[0]["ok"] is False
    assert not of(events, "action_proposed")


async def test_loop_stops_after_max_steps(uow: UnitOfWork, world: World) -> None:
    events = await run(uow, world.ravi, "keep searching forever")
    assert of(events, "token") == [{"text": OUT_OF_STEPS}]
    assert of(events, "done") == [{"steps": 6}]


def test_mock_turn_and_last_templating() -> None:
    msgs = [{"role": "user", "content": "x"}, {"role": "assistant", "content": None}]
    assert _turn(msgs) == 2
    last = {"ok": True, "data": {"tasks": [{"key": "T-1"}, {"key": "T-2"}]}}
    assert _fill({"tasks": "$last.data.tasks[].key", "n": 1}, last) == {
        "tasks": ["T-1", "T-2"],
        "n": 1,
    }


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


async def test_command_endpoint_streams_and_prefs(
    as_user: Clients, uow: UnitOfWork, world: World, settings: Settings
) -> None:
    ravi = await as_user("ravi")
    async with ravi.stream(
        "POST", "/api/v1/ai/command", json={"text": "Complete Draft pricing FAQ"}
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join([chunk async for chunk in r.aiter_text()])
    events = _events(body)
    assert [t for t, _ in events][-2:] == ["action_proposed", "done"]
    action_id = of(events, "action_proposed")[0]["action_id"]
    r = await ravi.post(f"/api/v1/ai/actions/{action_id}/apply", json={})
    assert r.status_code == 200 and r.json()["outcome"] == "applied"

    assert (await ravi.get("/api/v1/ai/prefs")).json() == {"auto_apply_low_risk": False}
    r = await ravi.put("/api/v1/ai/prefs", json={"auto_apply_low_risk": True})
    assert r.status_code == 200
    assert (await ravi.get("/api/v1/ai/prefs")).json() == {"auto_apply_low_risk": True}
    assert (await ravi.post("/api/v1/ai/command", json={"text": ""})).status_code == 422


async def test_ai_off_ends_the_stream_with_an_error_event(app_factory: Any, seeded: None) -> None:
    from tests.helpers import Clients as C

    app = app_factory(ai_enabled=False)
    async with app.router.lifespan_context(app):
        clients = C(app)
        ravi = await clients("ravi")
        async with ravi.stream("POST", "/api/v1/ai/command", json={"text": "hello"}) as r:
            body = "".join([chunk async for chunk in r.aiter_text()])
        await clients.close()
    assert _events(body) == [
        ("error", {"reason": "disabled", "message": "AI is turned off for this workspace."})
    ]
