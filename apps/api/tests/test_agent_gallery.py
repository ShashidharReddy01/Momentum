"""S5.2.3: create an agent from a description (drafted, checked, then saved through the normal
API) and test-run an agent without changing anything."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import func, select

from momentum.ai.models import AiAction
from momentum.domain.agents import service
from momentum.domain.agents.models import AgentRun
from momentum.domain.agents.schemas import AgentPatchIn
from tests.ai_fixtures import world
from tests.helpers import Clients, ctx_for
from tests.test_agent_runtime import TOOLS, Env, _comments, _defn, _task, make_env

_ = (make_env, world)


@pytest.fixture
async def scripted(app_factory: Any, seeded: None, tmp_path: Path) -> AsyncIterator[Clients]:
    """Clients of an app whose mock model reads this test's fixtures (``tmp_path``)."""
    app = app_factory(llm_fixtures_dir=str(tmp_path))
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        yield clients
        await clients.close()


async def test_a_drafted_agent_is_checked_against_the_rules(as_user: Clients) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    body = {"description": "A weekly bug sweeper that flags stale bugs"}
    assert (await ravi.post("/api/v1/agents/draft", json=body)).status_code == 403
    r = await admin.post("/api/v1/agents/draft", json=body)
    assert r.status_code == 200, r.text
    draft = r.json()
    agent = draft["agent"]
    assert agent["tools"] == ["search_tasks", "get_task", "add_comment"]
    assert agent["triggers"] == [
        {"type": "schedule", "cron": "0 9 * * MON", "timezone": "workspace"},
        {"type": "mentioned"},
    ]
    assert agent["autonomy"] == "confirm" and agent["model_alias"] == "fast"
    notes = " ".join(draft["notes"])
    assert "delete_task" in notes and "browse_web" in notes
    assert "invalid time" in notes and "Starts at confirm" in notes
    # the reviewed draft saves through the normal API, disabled
    saved = await admin.post("/api/v1/agents", json=agent)
    assert saved.status_code == 201, saved.text
    assert saved.json()["data"]["enabled"] is False
    assert saved.json()["data"]["source"] == "custom"


async def test_a_test_run_changes_nothing(
    make_env: Callable[..., Env], scripted: Clients, tmp_path: Path
) -> None:
    env = make_env()
    agent = await env.install(_defn())
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:  # testing is for agents that aren't on yet
        await service.update_agent(s, admin, agent.id, AgentPatchIn(enabled=False), TOOLS)
    (tmp_path / "agent_test__helper.yaml").write_text(
        yaml.safe_dump(
            {
                "responses": [
                    {
                        "match": {"turn": 1, "contains": "run now"},
                        "tool_calls": [
                            {
                                "name": "update_task",
                                "arguments": {
                                    "task": {"title_query": "Draft pricing copy"},
                                    "priority": "high",
                                },
                            }
                        ],
                    },
                    {
                        "match": {"turn": 2, "contains": "run now"},
                        "text": "(mock) I'd raise the priority.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    client = await scripted("admin")
    url = f"/api/v1/agents/{agent.id}/test-run"
    assert (await (await scripted("ravi")).post(url, json={"task": "T-1"})).status_code == 403
    number = (await _task(env, env.world.copy.id)).number
    r = await client.post(url, json={"task": f"T-{number}"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["text"] == "(mock) I'd raise the priority."
    [change] = out["changes"]
    assert change["tool"] == "update_task"
    assert change["decision"] == "would propose to the person who asked"
    assert any(s["kind"] == "tool" and s["name"] == "update_task" for s in out["trace"])
    # nothing happened: no run, no proposal, no comment, the task untouched
    assert (await _task(env, env.world.copy.id)).priority != "high"
    assert await _comments(env, env.world.copy.id) == []
    async with env.uow.transaction() as s:
        assert await s.scalar(select(func.count()).select_from(AgentRun)) == 0
        assert await s.scalar(select(func.count()).select_from(AiAction)) == 0
    # a task the agent can't reach says so
    hidden = (await _task(env, env.world.hidden.id)).number
    r = await client.post(url, json={"task": f"T-{hidden}"})
    assert r.status_code == 422 and "access" in r.text
