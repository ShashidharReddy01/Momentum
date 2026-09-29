"""S5.3.3 Herald · Status Reporter: one scheduled run per project it belongs to, for the owner; a
quiet week drafts nothing and calls no model; otherwise the S3.4.3 draft is proposed to the
owner to publish (billed to Herald's run); @mentioned on a task it answers in the thread."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from momentum.agents.loader import load_definitions
from momentum.agents.triggers import evaluate_schedules
from momentum.ai.actions import apply_action
from momentum.ai.models import AiAction, LlmCall
from momentum.domain.agents.models import AgentRun
from momentum.domain.agents.runs import enqueue_run
from momentum.domain.comments.service import create_comment
from momentum.domain.status_updates.models import StatusUpdate
from momentum.domain.tasks import service as tasks
from tests.ai_fixtures import REG, world
from tests.test_agent_runtime import Env, _comments, make_env

_ = (make_env, world)
HERALD = next(d for d, _s in load_definitions() if d.key == "status_reporter")


async def _runs(env: Env) -> list[AgentRun]:
    async with env.uow.transaction() as s:
        return list(
            (
                await s.execute(
                    select(AgentRun)
                    .where(AgentRun.agent_id == env.agent.id)
                    .order_by(AgentRun.created_at)
                )
            ).scalars()
        )


async def _billed(env: Env, run_id: Any) -> int:
    async with env.uow.transaction() as s:
        return int(
            await s.scalar(
                select(func.count()).select_from(LlmCall).where(LlmCall.agent_run_id == run_id)
            )
            or 0
        )


async def test_friday_queues_one_run_per_project_for_its_owner(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    await env.install(HERALD)  # a member of the world's project only
    friday = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)  # workspace timezone defaults to UTC
    async with env.uow.transaction() as s:
        await evaluate_schedules(s, env.settings, friday)
        again = await evaluate_schedules(s, env.settings, friday)  # delivered twice: once
    [run] = await _runs(env)
    assert again.queued == 0
    assert run.trigger["project_id"] == str(env.world.project.id)
    assert run.trigger["requested_by"] == str(env.world.ravi.actor.id)


async def test_a_quiet_week_drafts_nothing(make_env: Callable[..., Env]) -> None:
    env = make_env()
    await env.install(HERALD)
    async with env.uow.transaction() as s:
        trigger = {
            "type": "schedule",
            "project_id": str(env.world.project.id),
            "requested_by": str(env.world.ravi.actor.id),
        }
        await enqueue_run(s, env.agent, trigger, "k")
    assert await env.drain() == ["succeeded"]
    [run] = await _runs(env)
    assert await _billed(env, run.id) == 0
    assert (run.output or {}).get("proposed") == []
    assert any("Nothing happened" in s["summary"] for s in run.trace)


async def test_an_active_week_is_proposed_to_the_owner_and_billed_to_herald(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(llm_fixtures_dir="")  # the packaged status_draft mock
    await env.install(HERALD)
    async with env.uow.transaction() as s:
        await tasks.set_completed(s, env.world.ravi, env.world.copy.id, True)
        trigger = {
            "type": "schedule",
            "project_id": str(env.world.project.id),
            "requested_by": str(env.world.ravi.actor.id),
        }
        await enqueue_run(s, env.agent, trigger, "k")
    assert await env.drain() == ["succeeded"]
    [run] = await _runs(env)
    assert await _billed(env, run.id) >= 1  # draft_status's call counted on Herald's run
    async with env.uow.transaction() as s:
        [action] = list(
            (await s.execute(select(AiAction).where(AiAction.source_id == run.id))).scalars()
        )
        assert action.proposed_for == env.world.ravi.actor.id
        assert [op["tool"] for op in action.operations] == ["create_status_update"]
        before = await s.scalar(select(func.count()).select_from(StatusUpdate))
    assert before == 0  # nothing is published until the owner applies it
    async with env.uow.transaction() as s:
        await apply_action(s, env.world.ravi, REG, action.id)
    async with env.uow.transaction() as s:
        [update] = list((await s.execute(select(StatusUpdate))).scalars())
        assert update.entity_id == env.world.project.id
        assert update.author_id == env.world.ravi.actor.id


async def test_mentioned_on_a_task_it_answers_the_person_who_asked(
    make_env: Callable[..., Env],
) -> None:
    env = make_env(llm_fixtures_dir="")
    await env.install(HERALD)
    async with env.uow.transaction() as s:
        await tasks.set_completed(s, env.world.ravi, env.world.faq.id, True)
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "mention",
                            "attrs": {"id": str(env.account.id), "label": "Herald", "kind": "user"},
                        },
                        {"type": "text", "text": " draft a status please"},
                    ],
                }
            ],
        }
        await create_comment(s, env.world.ana, env.world.copy.id, doc)
    assert await env.events() == 1
    assert await env.drain() == ["succeeded"]
    *_, reply = await _comments(env, env.world.copy.id)
    assert reply.author_id == env.account.id
    text = " ".join(n.get("text", "") for p in reply.body["content"] for n in p.get("content", []))
    assert "waiting for you to review and publish" in text
    async with env.uow.transaction() as s:
        [action] = list((await s.execute(select(AiAction))).scalars())
        assert action.proposed_for == env.world.ana.actor.id
