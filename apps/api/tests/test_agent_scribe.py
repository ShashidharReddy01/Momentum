"""S5.3.6 Scribe: meeting notes (pasted, or a task's description and attachments) become
decisions plus proposed tasks, with owners only from the project and no dates in the past."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select

from momentum.agents.extensions import attach_file
from momentum.agents.loader import load_definitions
from momentum.agents.triggers import request_run
from momentum.ai.models import AiAction
from momentum.domain.tasks import service as tasks
from tests.ai_fixtures import world
from tests.test_agent_runtime import Env, _comments, make_env

_ = (make_env, world)
SCRIBE = next(d for d, _s in load_definitions() if d.key == "meeting_notes")
NOTES = (
    "Launch sync. Decided: ship on Friday October 9. Ana will write the FAQ by the 6th. "
    "Ravi to book the venue. Someone should update the pricing page. Zed calls the lawyer."
)


async def _ops(env: Env) -> list[dict]:  # type: ignore[type-arg]
    async with env.uow.transaction() as s:
        [action] = list(
            (await s.execute(select(AiAction).where(AiAction.source == "agent"))).scalars()
        )
        assert action.proposed_for == env.world.ravi.actor.id
        return list(action.operations)


async def test_pasted_notes_become_decisions_and_proposed_tasks(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(llm_fixtures_dir="")
    await env.install(SCRIBE)
    async with env.uow.transaction() as s:
        await request_run(s, env.world.ravi, env.agent, project_id=env.world.project.id, text=NOTES)
    assert await env.drain() == ["succeeded"]
    ops = await _ops(env)
    args = [op["args"] for op in ops]
    assert [op["tool"] for op in ops] == ["create_task"] * 5
    faq, venue, pricing, lawyer, recap = args
    assert faq["assignee"].startswith("ana@") and faq["due_on"] == "2030-10-06"
    assert venue["assignee"].startswith("ravi@") and "due_on" not in venue
    assert "assignee" not in pricing and "assignee" not in lawyer  # nobody / not on the project
    assert "due_on" not in recap  # a date in the past is dropped
    assert "From the meeting notes: (mock) Launch sync" in faq["description"]
    [run] = await env.runs()
    text = (run.output or {})["text"]
    assert "Decisions:\n- Ship on Friday, October 9" in text
    assert "Zed Unknown isn't on" in text and "dropped a date in the past" in text


async def test_notes_attached_to_a_task_are_read_and_answered_in_the_thread(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(llm_fixtures_dir="")
    await env.install(SCRIBE)
    async with env.uow.transaction() as s:
        meeting = (
            await tasks.create_task(s, env.world.ravi, env.world.project.id, "Launch sync")
        ).entity[0]
        await attach_file(
            s, env.world.ravi, env.settings, meeting.id, "notes.vtt", NOTES.encode(), "text/vtt"
        )
        await request_run(s, env.world.ravi, env.agent, task_id=meeting.id)
    assert await env.drain() == ["succeeded"]
    ops = await _ops(env)
    assert f"(from T-{meeting.number})" in ops[0]["args"]["description"]
    [run] = await env.runs()
    assert any("Read notes.vtt" in st["summary"] for st in run.trace)
    [reply] = await _comments(env, meeting.id)
    assert reply.author_id == env.account.id and "Action items" in reply.body_text
