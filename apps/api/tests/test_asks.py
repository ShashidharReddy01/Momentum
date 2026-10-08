"""Phase 7.6 S76-03 (spec §5): asks. Every kind round-trips (the job waits, a person answers,
the job continues with the answer); expiry defaults (a value, fail, route_to_review, escalate);
reminders; a thread reply answers when certain and is only proposed when not; guests never answer;
an answer is undoable until the job uses it; a job that ends cancels its asks; proposals; and
conversation runs (questions, and commands behind a confirm ask)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.agents.jobs import control
from momentum.agents.triggers import consume_events
from momentum.app import create_app
from momentum.core.activity import Activity
from momentum.core.db import UnitOfWork
from momentum.core.errors import Forbidden, ValidationFailed
from momentum.domain.asks import service as asks
from momentum.domain.asks.models import Ask
from momentum.domain.comments.models import Comment
from momentum.domain.comments.service import create_comment
from momentum.domain.notifications.models import Notification
from momentum.domain.users.models import User
from momentum.sdk import Job
from tests.ai_fixtures import REG, World, call, world
from tests.helpers import Clients, ctx_for
from tests.jobs_env import JobsEnv

_ = world
B = "/api/v1"

ANSWERS: dict[str, tuple[Any, Any]] = {
    # kind: (what the person gives, what the job gets)
    "choice": ("Globex", "globex"),
    "confirm": (True, True),
    "form": ({"amount": "1,250.00", "due": "2026-11-01"}, {"amount": 1250.0, "due": "2026-11-01"}),
    "text": ("PO-7781", "PO-7781"),
    "pick_entity": ("e2", "e2"),
    "pick_record": ("INV-2", "r2"),
}


@pytest.fixture
def make_env(
    uow: UnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    world: World,
) -> Callable[..., JobsEnv]:
    return lambda **kw: JobsEnv(uow, session_factory, tmp_path, world, **kw)


async def _ask_of(env: JobsEnv, run_id: uuid.UUID) -> Ask:
    async with env.uow.transaction() as s:
        row = await s.scalar(
            select(Ask)
            .where(Ask.run_id == run_id, Ask.status != "superseded")
            .execution_options(populate_existing=True)
        )
        assert row is not None
        return row


async def _start(env: JobsEnv, world: World, kind: str, who: Any = None) -> uuid.UUID:
    run_id = await env.start(task=world.copy, text=kind, who=who)
    assert await env.drain() == ["waiting"]
    return run_id


@pytest.mark.parametrize("kind", list(ANSWERS))
async def test_every_ask_kind_round_trips(
    make_env: Callable[..., JobsEnv], world: World, kind: str
) -> None:
    env = make_env()
    await env.install("asker")
    run_id = await _start(env, world, kind)
    run = await env.run(run_id)
    assert run.waiting_on is not None and run.waiting_on["type"] == "ask"
    ask = await _ask_of(env, run_id)
    assert ask.kind == kind and ask.status == "open"
    assert ask.to_user_ids == [world.ravi.actor.id]  # the person who ran it
    async with env.uow.transaction() as s:  # the card is the agent's comment with an askCard
        card = await s.get(Comment, ask.comment_id)
        assert card is not None and card.is_ai
        assert {"type": "askCard", "attrs": {"askId": str(ask.id)}} in card.body["content"]
        told = await s.scalar(
            select(Notification).where(
                Notification.user_id == world.ravi.actor.id, Notification.kind == "agent_ask"
            )
        )
        assert told is not None
    given, got = ANSWERS[kind]
    async with env.uow.transaction() as s:
        await asks.answer_ask(s, world.ravi, ask.id, given)
    assert (await env.run(run_id)).status == "queued"  # answering wakes the job
    assert await env.drain() == ["succeeded"]
    result = (await env.run(run_id)).output or {}
    assert result["result"]["status"] == "answered" and result["result"]["value"] == got


async def test_answers_are_validated_and_only_the_people_asked_may_answer(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("asker")
    run_id = await _start(env, world, "form")
    ask = await _ask_of(env, run_id)
    for bad in ({"amount": "lots"}, {"due": "2026-11-01"}, {"amount": 1, "colour": "red"}, "1250"):
        async with env.uow.transaction() as s:
            with pytest.raises(ValidationFailed):
                await asks.answer_ask(s, world.ravi, ask.id, bad)
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden):
            await asks.answer_ask(s, world.ana, ask.id, {"amount": 1})  # not asked
    async with env.uow.transaction() as s:
        await asks.answer_ask(s, world.ravi, ask.id, {"amount": 1})
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        ravi = await clients("ravi")
        r = await ravi.post(f"{B}/asks/{ask.id}/answer", json={"value": {"amount": 2}})
        assert r.status_code == 409  # already answered
        await clients.close()


async def test_guests_never_answer(make_env: Callable[..., JobsEnv], world: World) -> None:
    env = make_env()
    await env.install("asker")
    async with env.uow.transaction() as s:
        await s.execute(update(User).where(User.id == world.lena.actor.id).values(role="guest"))
    lena = await ctx_for(env.uow, env.settings, "lena")

    # a route to a guest falls back to the project owner, and the fallback is recorded
    async def run(job: Job) -> Any:
        return await job.ask(
            "q",
            kind="text",
            title="Anything?",
            route=f"person:{lena.actor.id}",
            default_on_expiry={"action": "fail"},
        )

    env.use("asker", run=run)
    run_id = await _start(env, world, "text")
    ask = await _ask_of(env, run_id)
    assert ask.to_user_ids == [world.ravi.actor.id] and ask.route_fallback == "project_owner"
    async with env.uow.transaction() as s:
        await s.execute(update(Ask).where(Ask.id == ask.id).values(to_user_ids=[lena.actor.id]))
    async with env.uow.transaction() as s:
        with pytest.raises(Forbidden):
            await asks.answer_ask(s, lena, ask.id, "yes")


@pytest.mark.parametrize(
    ("kind", "outcome"),
    [
        ("choice", ("succeeded", {"status": "expired", "value": "acme"})),
        ("pick_record", ("succeeded", {"status": "expired", "value": "r1"})),
        ("confirm", ("succeeded", {"status": "expired", "action": "route_to_review"})),
        ("form", ("failed", "Nobody answered")),
    ],
)
async def test_expiry_defaults(
    make_env: Callable[..., JobsEnv], world: World, kind: str, outcome: tuple[str, Any]
) -> None:
    env = make_env()
    await env.install("asker")
    run_id = await _start(env, world, kind)
    async with env.uow.transaction() as s:
        stats = await asks.ask_timers(s, env.settings, datetime.now(UTC) + timedelta(days=8))
    assert stats["expired"] == 1
    assert (await _ask_of(env, run_id)).status == "expired"
    status, expect = outcome
    assert await env.drain() == [status]
    run = await env.run(run_id)
    if status == "failed":
        assert expect in (run.error or "")
    else:
        result = (run.output or {})["result"]
        assert {k: result[k] for k in expect} == expect


async def test_escalation_goes_up_the_routes(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("asker")
    async with env.uow.transaction() as s:  # ana can edit the project and runs the agent
        from momentum.domain.projects.service import add_member

        await add_member(s, world.ravi, world.project.id, world.ana.actor.id, "editor")
    run_id = await _start(env, world, "text", who=world.ana)
    first = await _ask_of(env, run_id)
    assert first.to_user_ids == [world.ana.actor.id]
    async with env.uow.transaction() as s:
        await asks.ask_timers(s, env.settings, datetime.now(UTC) + timedelta(days=8))
    second = await _ask_of(env, run_id)
    assert second.id != first.id and second.route == "project_owner"
    assert second.to_user_ids == [world.ravi.actor.id]
    async with env.uow.transaction() as s:
        old = await s.get(Ask, first.id, populate_existing=True)
        assert old is not None and old.status == "superseded" and old.superseded_by == second.id
    assert (await env.run(run_id)).waiting_on == {
        "type": "ask",
        "ids": [str(second.id)],
        "key": "question",
    }
    async with env.uow.transaction() as s:
        await asks.answer_ask(s, world.ravi, second.id, "PO-1")
    assert await env.drain() == ["succeeded"]


async def test_reminders(make_env: Callable[..., JobsEnv], world: World) -> None:
    env = make_env()
    await env.install("asker")
    run_id = await _start(env, world, "choice")
    ask = await _ask_of(env, run_id)
    assert ask.remind_at is not None and ask.remind_at < ask.expires_at
    async with env.uow.transaction() as s:
        assert (await asks.ask_timers(s, env.settings, ask.remind_at))["reminded"] == 1
    again = await _ask_of(env, run_id)
    assert again.reminders_sent == 1 and again.remind_at is not None
    async with env.uow.transaction() as s:
        assert (await asks.ask_timers(s, env.settings, again.remind_at))["reminded"] == 1
    final = await _ask_of(env, run_id)
    assert final.reminders_sent == 2 and final.remind_at is None
    async with env.uow.transaction() as s:
        reminders = (
            await s.execute(select(Notification).where(Notification.kind == "agent_ask_reminder"))
        ).scalars()
        assert list(reminders)


def test_working_hours_skip_the_weekend() -> None:
    friday_noon = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    assert asks.add_working_hours(friday_noon, 24) == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    monday = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    assert asks.add_working_hours(monday, 5) == datetime(2026, 10, 12, 14, 0, tzinfo=UTC)


async def test_a_thread_reply_answers_when_certain_and_proposes_when_not(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    (env.tmp / "ask_interpret.yaml").write_text(
        yaml.safe_dump(
            {
                "responses": [
                    {
                        "match": {"contains": "twelve fifty"},
                        "tool_calls": [
                            {
                                "name": "answer",
                                "arguments": {
                                    "value": {"amount": 1250, "due": "2026-11-01"},
                                    "explanation": "Use 1,250.00",
                                },
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    await env.install("asker")
    choice_run = await _start(env, world, "choice")
    choice = await _ask_of(env, choice_run)
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        ravi = await clients("ravi")
        r = await ravi.post(f"{B}/asks/{choice.id}/interpret", json={"text": "globex."})
        assert r.status_code == 200, r.text
        assert r.json()["applied"] is True and r.json()["value"] == "globex"
        assert r.json()["ask"]["answered_via"] == "thread"
        await clients.close()

    form_run = await env.start(task=world.faq, text="form")
    await env.drain()
    form = await _ask_of(env, form_run)
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        ravi = await clients("ravi")
        r = await ravi.post(
            f"{B}/asks/{form.id}/interpret", json={"text": "make it twelve fifty, due 1 Nov"}
        )
        body = r.json()
        assert body["applied"] is False and body["certain"] is False  # never applied silently
        assert body["value"] == {"amount": 1250.0, "due": "2026-11-01"}
        assert "Amount = 1250.0" in body["understood"]
        assert body["ask"]["status"] == "open"
        r = await ravi.post(
            f"{B}/asks/{form.id}/answer", json={"value": body["value"], "via": "thread"}
        )
        assert r.json()["status"] == "answered"
        ana = await clients("ana")  # not asked: can't answer by replying either
        r = await ana.post(f"{B}/asks/{choice.id}/interpret", json={"text": "acme"})
        assert r.status_code in (403, 404)
        await clients.close()


async def test_an_answer_can_be_undone_until_the_job_uses_it(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    from momentum.core.undo import UndoConflict, undo

    env = make_env()
    await env.install("asker")
    run_id = await _start(env, world, "choice")
    ask = await _ask_of(env, run_id)
    async with env.uow.transaction() as s:
        await asks.answer_ask(s, world.ravi, ask.id, "acme")
        act = await s.scalar(
            select(Activity.id).where(Activity.entity_id == ask.id, Activity.verb == "ask.answered")
        )
    async with env.uow.transaction() as s:
        await undo(s, world.ravi, activity_id=act)
    assert (await _ask_of(env, run_id)).status == "open"
    assert await env.drain() == ["waiting"]  # replayed, still waiting on its question
    async with env.uow.transaction() as s:
        await asks.answer_ask(s, world.ravi, ask.id, "globex")
        act = await s.scalar(
            select(Activity.id)
            .where(Activity.entity_id == ask.id, Activity.verb == "ask.answered")
            .order_by(Activity.created_at.desc())
            .limit(1)
        )
    assert await env.drain() == ["succeeded"]
    async with env.uow.transaction() as s:
        with pytest.raises(UndoConflict, match="already used"):
            await undo(s, world.ravi, activity_id=act)


async def test_a_job_that_ends_cancels_its_asks(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("asker")
    run_id = await _start(env, world, "choice")
    async with env.uow.transaction() as s:
        await control.cancel(s, world.ravi, run_id)
    assert (await _ask_of(env, run_id)).status == "cancelled"


async def test_listing_my_asks_and_mo_reads_them(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    await env.install("asker")
    await _start(env, world, "choice")
    async with env.uow.transaction() as s:
        mine = await asks.list_asks(s, world.ravi)
        theirs = await asks.list_asks(s, world.ana)
    assert len(mine) == 1 and theirs == []
    out = await call(env.uow, world.ravi, "list_my_asks", {}, mode="execute")
    assert out.ok
    [item] = out.result.data["asks"]
    assert item["agent"] == "Asker" and item["question"] == "Which vendor sent this invoice?"
    assert item["options"] == ["Acme Ltd", "Globex"]
    app = create_app(env.settings)
    async with app.router.lifespan_context(app):
        clients = Clients(app)
        ravi = await clients("ravi")
        rows = (await ravi.get(f"{B}/asks", params={"mine": "true"})).json()["data"]
        assert [a["title"] for a in rows] == ["Which vendor sent this invoice?"]
        assert rows[0]["can_answer"] is True
        await clients.close()


async def test_people_cant_post_ask_cards(make_env: Callable[..., JobsEnv], world: World) -> None:
    env = make_env()
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Answer me"}]},
            {"type": "askCard", "attrs": {"askId": str(uuid.uuid4())}},
        ],
    }
    async with env.uow.transaction() as s:
        with pytest.raises(ValidationFailed, match="askCard"):
            await create_comment(s, world.ravi, world.copy.id, doc)


async def test_a_job_proposes_what_it_may_not_do_itself(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    from momentum.ai.models import AiAction

    async def run(job: Job) -> str:
        assert job.task_id is not None
        proposed = await job.propose(
            "p", "update_task", {"task": str(job.task_id), "due_on": "2026-12-01"}
        )
        return proposed.summary

    env = make_env()
    env.use("asker", run=run)
    await env.install("asker")
    run_id = await env.start(task=world.copy)
    assert await env.drain() == ["succeeded"]
    async with env.uow.transaction() as s:
        action = await s.scalar(select(AiAction).where(AiAction.source_id == run_id))
    assert action is not None and action.state == "proposed"
    assert action.proposed_for == world.ravi.actor.id
    _ = REG


async def _mention(env: JobsEnv, world: World, text: str) -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "mention",
                        "attrs": {"id": str(env.agent.user_id), "label": "Asker", "kind": "user"},
                    },
                    {"type": "text", "text": f" {text}"},
                ],
            }
        ],
    }
    async with env.uow.transaction() as s:
        await create_comment(s, world.ravi, world.copy.id, doc)
    async with env.uow.transaction() as s:
        await consume_events(s, env.settings, packs=env.packs)


async def test_conversation_answers_questions_and_confirms_commands(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    env = make_env()
    (env.tmp / "agent__asker.yaml").write_text(
        yaml.safe_dump(
            {
                "responses": [
                    {
                        "match": {"contains": "how many"},
                        "tool_calls": [{"name": "answer", "arguments": {"intent": "question"}}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    await env.install("asker")
    async with env.uow.transaction() as s:
        await consume_events(s, env.settings, packs=env.packs)  # from now on
    waiting = await _start(env, world, "wait")  # a job of the agent waiting for an instruction
    await _mention(env, world, "how many jobs do you have here?")
    assert await env.drain() == ["succeeded"]
    async with env.uow.transaction() as s:
        bodies = [
            c.body_text
            for c in (
                await s.execute(select(Comment).where(Comment.task_id == world.copy.id))
            ).scalars()
        ]
    assert any("I have 1 job(s) on this task." in (b or "") for b in bodies)

    await _mention(env, world, "skip this one")
    assert await env.drain() == ["waiting"]  # the confirm ask comes first
    from momentum.domain.agents.models import AgentRun

    async with env.uow.transaction() as s:
        convo = await s.scalar(
            select(AgentRun.id)
            .where(AgentRun.capability == "converse", AgentRun.status == "waiting")
            .limit(1)
        )
    assert convo is not None
    confirm = await _ask_of(env, convo)
    assert confirm.kind == "confirm" and confirm.title == "Shall I skip?"
    assert (await env.run(waiting)).status == "waiting"  # nothing acted before the yes
    async with env.uow.transaction() as s:
        await asks.answer_ask(s, world.ravi, confirm.id, True)
    statuses = await env.drain()
    assert statuses.count("succeeded") == 2
    assert (await env.run(waiting)).output == {"result": {"action": "skip"}}


async def test_conversation_actions_need_a_yes(
    make_env: Callable[..., JobsEnv], world: World
) -> None:
    async def converse(job: Job) -> str:
        await job.start_job("start", {"text": "confirm"})
        return "started"

    env = make_env()
    env.use("asker", converse=converse)
    await env.install("asker")
    async with env.uow.transaction() as s:
        await consume_events(s, env.settings, packs=env.packs)
    await _start(env, world, "choice")
    await _mention(env, world, "rerun please")
    assert await env.drain() == ["failed"]
    from momentum.domain.agents.models import AgentRun

    async with env.uow.transaction() as s:
        err = await s.scalar(select(AgentRun.error).where(AgentRun.capability == "converse"))
    assert "needs a confirm ask answered yes" in (err or "")
