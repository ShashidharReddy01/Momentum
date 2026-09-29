"""S5.3.5 Architect: a brief becomes a proposed project plan for the person who asked (planned in
their team), a task becomes proposed subtasks, and the capacity hook flags busy owners."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from momentum.agents.loader import load_definitions
from momentum.agents.triggers import request_run
from momentum.ai.models import AiAction
from momentum.domain.tasks import service as tasks
from momentum.domain.users.models import User
from tests.ai_fixtures import world
from tests.test_agent_runtime import Env, _assign, _comments, make_env

_ = (make_env, world)
ARCHITECT = next(d for d, _s in load_definitions() if d.key == "planner")
BRIEF = (
    "We are relaunching the website in two months. Discovery with customers first, then design "
    "and legal review of the new terms, copy, and a launch with an announcement. Ana leads design."
)


async def _actions(env: Env) -> list[AiAction]:
    async with env.uow.transaction() as s:
        return list((await s.execute(select(AiAction).where(AiAction.source == "agent"))).scalars())


async def test_a_brief_becomes_a_proposed_project_plan(make_env: Callable[..., Env]) -> None:
    env = make_env(llm_fixtures_dir="")  # packaged project_brief mock
    await env.install(ARCHITECT)
    w = env.world
    async with env.uow.transaction() as s:  # Ana is already busy in the plan's window
        ana = (await s.execute(select(User).where(User.email.like("ana@%")))).scalar_one()
        for n in range(8):
            t = (await tasks.create_task(s, w.ravi, w.project.id, f"Busy {n}")).entity[0]
            await tasks.update_task(
                s,
                w.ravi,
                t.id,
                {"assignee_id": ana.id, "due_on": datetime.now(UTC).date() + timedelta(days=10)},
            )
        # no project: Ravi is in several teams, so Architect asks which one
        await request_run(s, w.ravi, env.agent, text=BRIEF)
    assert await env.drain() == ["succeeded"]
    assert await _actions(env) == []
    [asked] = await env.runs()
    assert "Which team is this project for?" in (asked.output or {})["text"]
    async with env.uow.transaction() as s:  # run from one of the team's projects
        await request_run(s, w.ravi, env.agent, project_id=w.project.id, text=BRIEF)
    assert await env.drain() == ["succeeded"]
    *_, planned = await env.runs()
    assert not any(s["kind"] == "skipped" for s in planned.trace), planned.trace
    [action] = await _actions(env)
    assert action.proposed_for == w.ravi.actor.id
    assert [op["tool"] for op in action.operations] == ["create_project_from_plan"]
    *_, run = await env.runs()
    text = (run.output or {})["text"]
    assert "Proposed a plan for (mock) Brief rollout" in text
    assert "Capacity: Ana Souza already has" in text  # 8 of ours, plus the seed's
    assert "Open question: Who signs off on pricing?" in text


async def test_an_assigned_task_gets_proposed_subtasks(make_env: Callable[..., Env]) -> None:
    env = make_env(llm_fixtures_dir="")  # packaged breakdown mock
    await env.install(ARCHITECT)
    await _assign(env, env.world.copy, env.world.ana)
    await env.events()
    assert await env.drain() == ["succeeded"]
    [action] = await _actions(env)
    assert action.proposed_for == env.world.ana.actor.id
    assert [op["tool"] for op in action.operations] == ["create_subtasks"]
    [reply] = await _comments(env, env.world.copy.id)
    assert reply.author_id == env.account.id
    assert "subtasks for you to review" in reply.body_text
