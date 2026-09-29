"""S5.2.1 + S5.3.8: assigning a task to an agent (J10's backend). Agents in the assignee picker,
the answer in the thread @mentioning whoever assigned it, a long answer attached as a file, the
hand-back for review ("Review" section, else the creator), and a run that didn't finish telling
the person who asked. Plus the Teammate starter end to end on its packaged mock fixture."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select

from momentum.agents.runtime import LONG_ANSWER
from momentum.domain.agents import service
from momentum.domain.agents.models import Agent
from momentum.domain.agents.schemas import AgentPatchIn
from momentum.domain.attachments.models import Attachment
from momentum.domain.notifications.models import Notification
from momentum.domain.sections.service import create_section
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import TaskProject
from momentum.domain.users.models import User
from tests.ai_fixtures import world
from tests.helpers import Clients, ctx_for
from tests.test_agent_runtime import (
    TOOLS,
    Env,
    _assign,
    _comments,
    _defn,
    _task,
    make_env,
)

_ = (make_env, world)

ANSWER = "(mock) Draft ready: three pricing tiers, per seat, based on [T-1]."


def _answer_script(env: Env, text: str = ANSWER) -> None:
    env.script(
        [
            {"match": {"contains": "assigned you the task", "turn": 1}, "text": text},
            {"match": {"contains": "mentioned you", "turn": 1}, "text": text},
        ]
    )


async def _notifications(env: Env, user_id: object, kind: str) -> list[Notification]:
    async with env.uow.transaction() as s:
        return list(
            (
                await s.execute(
                    select(Notification).where(
                        Notification.user_id == user_id, Notification.kind == kind
                    )
                )
            ).scalars()
        )


async def test_assignable_agents_are_offered_in_the_picker(
    make_env: Callable[..., Env], as_user: Clients
) -> None:
    env = make_env()
    helper = await env.install(_defn())  # enabled, acts when assigned
    admin = await ctx_for(env.uow, env.settings, "admin")
    async with env.uow.transaction() as s:
        # an enabled agent that only runs on a schedule, and a disabled assignable one
        [sched] = await service.install_definitions(
            s,
            admin,
            [(_defn(key="sched", name="Sched", triggers=[{"type": "manual"}]), "host")],
            TOOLS,
        )
        await service.update_agent(s, admin, sched.agent.id, AgentPatchIn(enabled=True), TOOLS)
        await service.install_definitions(s, admin, [(_defn(key="off", name="Off"), "host")], TOOLS)
    ravi = await as_user("ravi")

    async def names(query: str) -> set[str]:
        r = await ravi.get(f"/api/v1/users?limit=200{query}")
        assert r.status_code == 200
        return {u["name"] for u in r.json()["data"] if u["is_agent"]}

    assert await names("") == set()  # people only, as before
    assert await names("&agents=assigned") == {helper.name}
    assert await names("&agents=mentioned") == {helper.name}
    assert await names("&agents=all") == {helper.name, "Sched", "Off"}
    assert (await ravi.get("/api/v1/users?agents=everyone")).status_code == 422


async def test_the_answer_mentions_the_assigner_and_the_task_goes_back_to_its_creator(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    await env.install(_defn())
    _answer_script(env)
    # ravi created the task; ana assigns it to the agent
    await _assign(env, env.world.copy, env.world.ana)
    await env.events()
    assert await env.drain() == ["succeeded"]

    [comment] = await _comments(env, env.world.copy.id)
    first = comment.body["content"][0]["content"]
    assert first[0]["type"] == "mention"
    assert first[0]["attrs"]["id"] == str(env.world.ana.actor.id)
    assert "Draft ready" in first[-1]["text"]
    assert [n.entity_id for n in await _notifications(env, env.world.ana.actor.id, "mentioned")]

    task = await _task(env, env.world.copy.id)
    assert task.assignee_id == env.world.ravi.actor.id  # handed back to the creator
    [run] = await env.runs()
    assert run.output is not None
    assert run.output["handoff"] == {"assignee_id": str(env.world.ravi.actor.id)}
    assert any(s["kind"] == "handoff" and "Ravi" in s["summary"] for s in run.trace)


async def test_a_review_section_takes_the_task_instead(make_env: Callable[..., Env]) -> None:
    env = make_env()
    await env.install(_defn())
    _answer_script(env)
    async with env.uow.transaction() as s:
        review = (
            await create_section(
                s, env.world.ravi, env.world.project.id, "Review", after_id=env.world.doing.id
            )
        ).entity
    await _assign(env, env.world.copy, env.world.ravi)
    await env.events()
    assert await env.drain() == ["succeeded"]
    task = await _task(env, env.world.copy.id)
    assert task.assignee_id == env.account.id  # stays with the agent, in Review
    async with env.uow.transaction() as s:
        placement = (
            await s.execute(select(TaskProject).where(TaskProject.task_id == task.id))
        ).scalar_one()
    assert placement.section_id == review.id


async def test_a_long_answer_is_attached_as_a_file(make_env: Callable[..., Env]) -> None:
    env = make_env()
    await env.install(_defn())
    paragraph = "Findings on per-seat pricing across the market, with the numbers we have. "
    long_text = "\n".join([paragraph * 6] * (LONG_ANSWER // (len(paragraph) * 6) + 2))
    assert len(long_text) > LONG_ANSWER
    _answer_script(env, long_text)
    await _assign(env, env.world.copy, env.world.ravi)
    await env.events()
    assert await env.drain() == ["succeeded"]
    [comment] = await _comments(env, env.world.copy.id)
    text = "".join(n.get("text", "") for p in comment.body["content"] for n in p.get("content", []))
    assert len(text) < LONG_ANSWER
    assert "attached file helper-T-" in text
    async with env.uow.transaction() as s:
        [att] = list(
            (
                await s.execute(select(Attachment).where(Attachment.task_id == env.world.copy.id))
            ).scalars()
        )
    assert att.filename.endswith(".md") and att.mime == "text/markdown"
    assert att.size_bytes == len(long_text.strip().encode())
    assert att.uploaded_by == env.account.id


async def test_no_hand_off_when_someone_reassigned_it_meanwhile(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    await env.install(_defn())
    _answer_script(env)
    await _assign(env, env.world.copy, env.world.ravi)
    await env.events()
    async with env.uow.transaction() as s:
        await tasks.update_task(
            s, env.world.ravi, env.world.copy.id, {"assignee_id": env.world.ana.actor.id}
        )
    assert await env.drain() == ["succeeded"]
    assert (await _task(env, env.world.copy.id)).assignee_id == env.world.ana.actor.id
    [run] = await env.runs()
    assert any("reassigned or completed meanwhile" in s["summary"] for s in run.trace)


async def test_a_run_that_cannot_finish_tells_the_person_who_asked(
    make_env: Callable[..., Env],
) -> None:
    env = make_env()
    await env.install(_defn(), access=False)
    await _assign(env, env.world.copy, env.world.ravi)
    await env.events()
    assert await env.drain() == ["failed"]
    [run] = await env.runs()
    [alert] = await _notifications(env, env.world.ravi.actor.id, "agent_alert")
    assert alert.entity_type == "agent_run" and alert.entity_id == run.id
    assert "access" in (alert.snippet or "")
    # the task stays with the agent: nothing was handed back and nothing posted
    assert (await _task(env, env.world.copy.id)).assignee_id == env.account.id
    assert await _comments(env, env.world.copy.id) == []


async def test_the_teammate_starter_does_assigned_work_in_mock_mode(
    make_env: Callable[..., Env], as_user: Clients
) -> None:
    """S5.3.8 on its packaged definition and mock fixture (what J10 runs in the browser)."""
    env = make_env(llm_fixtures_dir="")
    admin = await as_user("admin")
    assert (await admin.post("/api/v1/agents/install", json={"keys": ["teammate"]})).is_success
    async with env.uow.transaction() as s:
        agent = (await s.execute(select(Agent).where(Agent.key == "teammate"))).scalar_one()
        await service.update_agent(
            s,
            await ctx_for(env.uow, env.settings, "admin"),
            agent.id,
            AgentPatchIn(enabled=True),
            TOOLS,
        )
        await service.add_to_project(s, env.world.ravi, agent.id, env.world.project.id, "editor")
        account = await s.get(User, agent.user_id)
        assert account is not None
    env.agent, env.account = agent, account
    await _assign(env, env.world.copy, env.world.ravi)
    await env.events()
    assert await env.drain() == ["succeeded"]
    [comment] = await _comments(env, env.world.copy.id)
    assert comment.author_id == account.id and comment.is_ai
    body = "".join(n.get("text", "") for p in comment.body["content"] for n in p.get("content", []))
    assert "mock" in body.lower()  # mock output always says so
    assert (await _task(env, env.world.copy.id)).assignee_id == env.world.ravi.actor.id
