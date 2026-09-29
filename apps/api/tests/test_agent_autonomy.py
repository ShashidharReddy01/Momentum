"""S5.1.4: autonomy promotion (earned, admin-only), automatic demotion, the workspace's
"allow medium auto" switch, and the stats behind the agent's settings panel."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from momentum.agents.autonomy import run_demotions
from momentum.agents.triggers import request_run
from momentum.ai.models import AiAction
from momentum.core.activity import Activity
from momentum.core.errors import ValidationFailed
from momentum.domain.agents import service
from momentum.domain.agents.models import Agent, AgentRun
from momentum.domain.agents.schemas import AgentIn, AgentPatchIn
from momentum.domain.agents.stats import agent_stats
from momentum.domain.notifications.models import Notification
from momentum.domain.tasks.models import Task
from momentum.domain.workspace.service import AiConfig, effective_ai, set_ai_config
from tests.ai_fixtures import world
from tests.conftest import make_settings
from tests.helpers import Clients, ctx_for
from tests.test_agent_runtime import TOOLS, Env, _defn, make_env

_ = (world, make_env)


async def _history(
    env: Env,
    states: list[str],
    *,
    by_agent: bool = False,
    at: datetime | None = None,
    undone_activity: bool = False,
) -> list[uuid.UUID]:
    """Record past actions of the agent: decided by a person (proposals) or by the agent itself
    (auto-applied)."""
    now = at or datetime.now(UTC)
    ids = []
    async with env.uow.transaction() as s:
        agent = await _agent(env, s)
        run = AgentRun(
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            trigger={"type": "manual"},
            status="succeeded",
        )
        s.add(run)
        await s.flush()
        for state in states:
            a = AiAction(
                workspace_id=agent.workspace_id,
                source="agent",
                source_id=run.id,
                proposed_for=env.world.ravi.actor.id,
                summary="x",
                operations=[],
                risk="low",
                state=state,
                decided_by=agent.user_id if by_agent else env.world.ravi.actor.id,
                decided_at=now,
                expires_at=now + timedelta(days=1),
            )
            s.add(a)
            await s.flush()
            ids.append(a.id)
            if undone_activity and state == "undone":
                s.add(
                    Activity(
                        workspace_id=agent.workspace_id,
                        actor_id=agent.user_id,
                        actor_kind="agent",
                        entity_type="task",
                        entity_id=env.world.copy.id,
                        verb="task.updated",
                        ai_action_id=a.id,
                        undone_at=now,
                    )
                )
    return ids


async def _agent(env: Env, s: Any) -> Agent:
    """The test agent, loaded fresh (a refused change rolls back and expires loaded objects)."""
    return (await s.execute(select(Agent).where(Agent.key == "helper"))).scalar_one()


async def _promote(env: Env) -> Any:
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        agent = await _agent(env, s)
        return await service.update_agent(s, admin, agent.id, AgentPatchIn(autonomy="auto"), TOOLS)


async def test_auto_must_be_earned(make_env: Callable[..., Env]) -> None:
    env = make_env()
    await env.install(_defn())
    with pytest.raises(ValidationFailed, match=r"Needs 30 decided proposals to judge \(has 0\)"):
        await _promote(env)
    await _history(env, ["applied"] * 25 + ["rejected"] * 5)  # 83%
    with pytest.raises(ValidationFailed, match=r"Acceptance 25/30 is below 85%"):
        await _promote(env)
    await _history(env, ["applied"] * 30, at=datetime.now(UTC) + timedelta(seconds=5))
    m = await _promote(env)  # the last 30 are all accepted
    assert m.entity.autonomy == "auto"


async def test_a_recent_undo_blocks_promotion(make_env: Callable[..., Env]) -> None:
    env = make_env()
    await env.install(_defn())
    await _history(env, ["applied"] * 29 + ["undone"], undone_activity=True)
    async with env.uow.transaction() as s:
        agent = await s.get(Agent, env.agent.id)
        assert agent is not None
        stats = await agent_stats(s, agent)
    assert stats.acceptance_rate == 1.0 and stats.undos_14d == 1 and not stats.eligible_for_auto
    with pytest.raises(ValidationFailed, match="undone in the last 14 days"):
        await _promote(env)


async def test_new_custom_agents_cannot_start_at_auto(make_env: Callable[..., Env]) -> None:
    env = make_env()
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        with pytest.raises(ValidationFailed, match="earned it"):
            await service.create_agent(s, admin, AgentIn(name="Eager", autonomy="auto"), TOOLS)


async def test_too_many_undos_demote_an_agent_and_tell_the_admins(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    await env.install(_defn(autonomy="auto"))  # shipped defaults may start at auto
    await _history(env, ["applied"] * 9 + ["undone"], by_agent=True)  # 10%: not over
    async with env.uow.transaction() as s:
        assert (await run_demotions(s, env.settings)).demoted == []
    await _history(env, ["undone"], by_agent=True)  # 2 of 11
    async with env.uow.transaction() as s:
        assert (await run_demotions(s, env.settings)).demoted == ["helper"]
    async with env.uow.transaction() as s:
        agent = await s.get(Agent, env.agent.id)
        act = (
            (
                await s.execute(
                    select(Activity).where(
                        Activity.entity_id == env.agent.id, Activity.verb == "agent.updated"
                    )
                )
            )
            .scalars()
            .all()[-1]
        )
        alert = (
            await s.execute(select(Notification).where(Notification.kind == "agent_alert"))
        ).scalar_one()
    assert agent is not None and agent.autonomy == "confirm"
    assert act.actor_id is None and "2 of the 11" in str(act.diff)
    assert "asks before changing" in alert.title
    # old undos (outside the week) don't count
    async with env.uow.transaction() as s:
        assert (await run_demotions(s, env.settings)).demoted == []


async def test_medium_risk_changes_need_the_workspace_switch(
    make_env: Callable[..., Env],
) -> None:
    settings = make_settings()
    assert effective_ai(settings, AiConfig()).allow_medium_auto is False
    env = make_env()
    await env.install(_defn(autonomy="auto", tools=["bulk_update_tasks", "get_task"]))
    script = [
        {
            "match": {"contains": "asked you to run", "turn": 1},
            "tool_calls": [
                {
                    "name": "bulk_update_tasks",
                    "arguments": {
                        "tasks": ["Draft pricing copy", "Draft pricing FAQ"],
                        "due_on": "2026-12-01",
                    },
                }
            ],
        },
        {"match": {"contains": "asked you to run", "turn": 2}, "text": "(mock) Moved both."},
    ]
    env.script(script)

    async def run_once() -> str:
        async with env.uow.transaction() as s:
            await request_run(s, env.world.ravi, env.agent, task_id=env.world.copy.id)
        await env.drain()
        async with env.uow.transaction() as s:
            action = (
                (await s.execute(select(AiAction).order_by(AiAction.created_at.desc())))
                .scalars()
                .first()
            )
            assert action is not None and action.risk == "medium"
            return action.state

    assert await run_once() == "proposed"  # off by default: proposed to ravi
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        await set_ai_config(s, admin, AiConfig(allow_medium_auto=True))
    assert await run_once() == "applied"
    async with env.uow.transaction() as s:
        task = await s.get(Task, env.world.copy.id)
    assert task is not None and str(task.due_on) == "2026-12-01"


async def test_stats_endpoint_is_for_admins(as_user: Clients) -> None:
    admin, ravi = await as_user("admin"), await as_user("ravi")
    await admin.post("/api/v1/agents/install", json={"keys": ["teammate"]})
    teammate = next(
        a for a in (await admin.get("/api/v1/agents")).json()["data"] if a["key"] == "teammate"
    )
    assert (await ravi.get(f"/api/v1/agents/{teammate['id']}/stats")).status_code == 403
    r = await admin.get(f"/api/v1/agents/{teammate['id']}/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decided"] == 0 and body["eligible_for_auto"] is False and body["reasons"]
    assert body["month_usd"] == "0" and body["priced"] is False
    r = await admin.patch(f"/api/v1/agents/{teammate['id']}", json={"autonomy": "auto"})
    assert r.status_code == 422 and "can't act on its own yet" in r.text
    # the medium-auto switch round-trips through the AI settings page's API
    r = await admin.put("/api/v1/ai/admin/settings", json={"allow_medium_auto": True})
    assert r.status_code == 200 and r.json()["data"]["allow_medium_auto"] is True
