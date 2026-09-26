"""S3.3.1 Ask Mo chat: the J8 shape (search → answer with citations), citations resolved as the
reader (never a link to something missing or private), uncertainty when retrieval is empty,
multi-turn history, write proposals from chat, feedback, privacy of conversations, and the SSE
endpoint."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from momentum.ai import citations
from momentum.ai.chat import EMPTY_RETRIEVAL, run_chat, start_turn
from momentum.ai.context import Screen
from momentum.ai.llm import LLM, build_llm
from momentum.ai.loop import OUT_OF_STEPS
from momentum.ai.mock import MockTransport, _fill_text, _turn
from momentum.ai.models import AiAction, AiConversation, AiMessage
from momentum.ai.types import ChatRequest, RawCompletion
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from momentum.domain.tasks import service as tasks
from tests.ai_fixtures import REG, World, key, world
from tests.conftest import make_settings
from tests.helpers import Clients

_ = world
NOW = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)


class SpyTransport(MockTransport):
    """Mock answers, and every request kept for assertions about what was sent."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.requests: list[ChatRequest] = []

    def resolve(self, req: ChatRequest) -> RawCompletion:
        self.requests.append(req)
        return super().resolve(req)


def spy_llm() -> tuple[LLM, SpyTransport]:
    settings = make_settings()
    llm = build_llm(settings)
    spy = SpyTransport(settings)
    llm.transport = spy
    return llm, spy


async def ask(
    uow: UnitOfWork,
    ctx: Any,
    text: str,
    *,
    conversation_id: uuid.UUID | None = None,
    llm: LLM | None = None,
    screen: Screen | None = None,
) -> tuple[uuid.UUID, list[tuple[str, dict[str, Any]]]]:
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(t: str, d: dict[str, Any]) -> None:
        events.append((t, d))

    ctx = ctx.with_(via="ai")
    screen = screen or Screen(kind="home")
    async with uow.transaction() as s:
        turn = await start_turn(s, ctx, text, conversation_id=conversation_id, screen=screen)
        ids = (turn.conversation.id, turn.message.id)
    async with uow.transaction() as s:
        await run_chat(
            s,
            llm or build_llm(make_settings()),
            ctx,
            REG,
            ids,
            screen=screen,
            now=NOW,
            emit=emit,
        )
    return ids[0], events


async def index_all(uow: UnitOfWork) -> None:
    """Build the embeddings the worker's indexing job would (the keyword half of retrieval
    needs every word of a question to match, so natural questions rely on the vector half)."""
    from momentum.ai.embeddings import reindex

    async with uow.transaction() as s:
        await reindex(s, build_llm(make_settings()))


def of(events: list[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [d for t, d in events if t == kind]


def answer(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(d["text"] for d in of(events, "token"))


async def messages(uow: UnitOfWork, conv_id: uuid.UUID) -> list[AiMessage]:
    async with uow.transaction() as s:
        return list(
            (
                await s.execute(
                    select(AiMessage)
                    .where(AiMessage.conversation_id == conv_id)
                    .order_by(AiMessage.created_at, AiMessage.id)
                )
            ).scalars()
        )


async def test_j8_shape_answer_streams_with_valid_citations(uow: UnitOfWork, world: World) -> None:
    conv_id, events = await ask(uow, world.ravi, "Which tasks are about pricing?")
    kinds = [t for t, _ in events]
    assert kinds[0] == "conversation" and kinds[-1] == "done"
    assert kinds.index("tool_call") < kinds.index("tool_result") < kinds.index("token")
    assert of(events, "tool_result")[0]["name"] == "semantic_search"
    text = answer(events)
    assert f"[{key(world.copy)}]" in text and f"[{key(world.faq)}]" in text
    cites = of(events, "citation")
    assert cites and all(c["valid"] for c in cites)
    by_key = {c["key"]: c for c in cites}
    assert by_key[key(world.copy)]["id"] == str(world.copy.id)
    # priya's private task also says "pricing"; ravi's search never surfaces it
    assert key(world.hidden) not in text
    (done,) = of(events, "done")
    assert done["grounded"] is True
    stored = await messages(uow, conv_id)
    assert [m.role for m in stored] == ["user", "assistant"]
    mo = stored[1]
    assert mo.content["text"] == text.strip()
    assert mo.content["steps"][0]["name"] == "semantic_search"
    assert mo.content["grounded"] is True and mo.tokens_in > 0 and mo.tokens_out > 0
    assert str(mo.id) == done["message_id"]


async def test_citations_resolve_as_the_reader(uow: UnitOfWork, world: World) -> None:
    text = (
        f"[{key(world.copy)}] [{key(world.hidden)}] [T-999999] [P:AI Tools Lab] "
        f"[P:Secret Plans] [P:no such] [{key(world.copy)}]"
    )
    async with uow.transaction() as s:
        as_ravi = await citations.resolve(s, world.ravi, text)
        as_priya = await citations.resolve(s, world.priya, text)
        as_tom = await citations.resolve(s, world.tom, text)
    assert [(c.ref, c.valid) for c in as_ravi] == [
        (f"[{key(world.copy)}]", True),  # repeated refs appear once
        (f"[{key(world.hidden)}]", False),  # private to priya: not a link for ravi
        ("[T-999999]", False),
        ("[P:AI Tools Lab]", True),
        ("[P:Secret Plans]", False),
        ("[P:no such]", False),
    ]
    assert [c.valid for c in as_priya][:2] == [True, True]
    assert as_ravi[0].title == "Draft pricing copy" and as_ravi[1].title is None
    assert not any(c.valid for c in as_tom)  # tom can't see the project at all


async def test_made_up_citations_never_become_links(uow: UnitOfWork, world: World) -> None:
    _, events = await ask(uow, world.ravi, "Cite something made up")
    assert [(c["ref"], c["valid"]) for c in of(events, "citation")] == [
        ("[T-999999]", False),
        ("[P:No Such Project]", False),
        ("[P:AI Tools Lab]", True),
    ]
    assert of(events, "done")[0]["grounded"] is True
    # citing only things that don't resolve is not grounded
    _, events = await ask(uow, world.ravi, "Cite only made up things")
    assert [c["valid"] for c in of(events, "citation")] == [False]
    assert of(events, "done")[0]["grounded"] is False


async def test_empty_retrieval_is_said_not_guessed(uow: UnitOfWork, world: World) -> None:
    llm, spy = spy_llm()
    conv_id, events = await ask(uow, world.ravi, "zebra xylophone quarterly", llm=llm)
    system = spy.requests[0].messages[0]["content"]
    assert EMPTY_RETRIEVAL in system and "No matching content found." in system
    assert "couldn't find" in answer(events)
    assert of(events, "citation") == []
    assert of(events, "done")[0]["grounded"] is False
    (_, mo) = await messages(uow, conv_id)
    assert mo.content["retrieved"] == 0 and mo.content["grounded"] is False


async def test_retrieval_found_something_no_uncertainty_note(uow: UnitOfWork, world: World) -> None:
    await index_all(uow)
    llm, spy = spy_llm()
    await ask(uow, world.ravi, "Which tasks are about pricing?", llm=llm)
    system = spy.requests[0].messages[0]["content"]
    assert EMPTY_RETRIEVAL not in system and f"[{key(world.copy)}]" in system
    assert key(world.hidden) not in system  # priya's private task isn't retrieved for ravi


async def test_follow_up_carries_history_and_screen_context(uow: UnitOfWork, world: World) -> None:
    llm, spy = spy_llm()
    screen = Screen(kind="project", project_id=world.project.id)
    conv_id, _ = await ask(
        uow, world.ravi, "Which tasks are about pricing?", llm=llm, screen=screen
    )
    spy.requests.clear()
    same, events = await ask(
        uow, world.ravi, "And who owns them?", conversation_id=conv_id, llm=llm, screen=screen
    )
    assert same == conv_id
    assert answer(events) == "None of them has an assignee yet."
    sent = spy.requests[0].messages
    roles = [m["role"] for m in sent]
    assert roles == ["system", "user", "assistant", "user"]
    assert "about pricing" in sent[1]["content"] and sent[1]["content"].startswith("<data")
    assert f"[{key(world.copy)}]" in sent[2]["content"]
    # the project on screen is in the deep context
    assert "AI Tools Lab" in sent[0]["content"] and "<project" in sent[0]["content"]
    async with uow.transaction() as s:
        conv = await s.get(AiConversation, conv_id)
        assert conv is not None and conv.context_type == "project"
        assert conv.context_id == world.project.id
        assert conv.title == "Which tasks are about pricing?"
    assert len(await messages(uow, conv_id)) == 4


async def test_chat_proposes_changes_as_an_action(uow: UnitOfWork, world: World) -> None:
    conv_id, events = await ask(uow, world.ravi, "Please complete Draft pricing FAQ")
    (proposed,) = of(events, "action_proposed")
    async with uow.transaction() as s:
        action = await s.get(AiAction, uuid.UUID(proposed["action_id"]))
        assert action is not None and action.source == "chat" and action.source_id == conv_id
    (_, mo) = await messages(uow, conv_id)
    assert mo.content["action_id"] == proposed["action_id"]
    async with uow.transaction() as s:
        t, _, _ = await tasks.get_task(s, world.ravi, world.faq.id)
        assert t.completed_at is None  # a preview only
    # only the person it was proposed for can rate it
    from momentum.ai.chat import set_feedback
    from momentum.core.errors import NotFound

    action_id = uuid.UUID(proposed["action_id"])
    async with uow.transaction() as s:
        fb = await set_feedback(
            s, world.ravi, target_type="ai_action", target_id=action_id, rating=1, comment=None
        )
        assert fb.rating == 1
    try:
        async with uow.transaction() as s:
            await set_feedback(
                s, world.ana, target_type="ai_action", target_id=action_id, rating=-1, comment=None
            )
        raise AssertionError("expected NotFound")
    except NotFound:
        pass


async def test_out_of_steps_is_streamed(uow: UnitOfWork, world: World) -> None:
    _, events = await ask(uow, world.ravi, "keep looking forever")
    assert answer(events).endswith(OUT_OF_STEPS)
    assert of(events, "done")[0]["steps"] == 8


async def test_conversations_are_private(uow: UnitOfWork, world: World) -> None:
    conv_id, _ = await ask(uow, world.ravi, "zebra xylophone quarterly")
    from momentum.ai.chat import get_conversation, list_conversations, set_feedback
    from momentum.core.errors import NotFound

    async with uow.transaction() as s:
        assert [c.id for c in await list_conversations(s, world.ravi)] == [conv_id]
        assert await list_conversations(s, world.ana) == []
    for fn in (
        lambda s: get_conversation(s, world.ana, conv_id),
        lambda s: start_turn(s, world.ana, "hi", conversation_id=conv_id, screen=Screen()),
    ):
        try:
            async with uow.transaction() as s:
                await fn(s)
            raise AssertionError("expected NotFound")
        except NotFound:
            pass
    (_, mo) = await messages(uow, conv_id)
    try:
        async with uow.transaction() as s:
            await set_feedback(
                s, world.ana, target_type="ai_message", target_id=mo.id, rating=1, comment=None
            )
        raise AssertionError("expected NotFound")
    except NotFound:
        pass


def test_mock_turns_restart_per_question_and_text_slots() -> None:
    msgs = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    assert _turn(msgs) == 1
    assert _turn([*msgs, {"role": "assistant", "content": None}, {"role": "tool"}]) == 2
    last = {"data": {"results": [{"cite": "[T-1]"}, {"cite": "[T-2]"}], "n": 0}}
    assert _fill_text("x {{$last.data.results[].cite}} y", last) == "x [T-1] [T-2] y"
    assert _fill_text("{{$last.data.missing}}", last) == "(none)"


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


async def test_chat_endpoints_history_and_feedback(
    as_user: Clients, uow: UnitOfWork, world: World
) -> None:
    ravi = await as_user("ravi")
    async with ravi.stream(
        "POST",
        "/api/v1/ai/chat",
        json={"text": "Which tasks are about pricing?", "screen": {"kind": "home"}},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _events("".join([chunk async for chunk in r.aiter_text()]))
    conv_id = of(events, "conversation")[0]["conversation_id"]
    message_id = of(events, "done")[0]["message_id"]
    async with ravi.stream(
        "POST", "/api/v1/ai/chat", json={"text": "And who owns them?", "conversation_id": conv_id}
    ) as r:
        events2 = _events("".join([chunk async for chunk in r.aiter_text()]))
    assert of(events2, "conversation")[0]["conversation_id"] == conv_id

    listing = (await ravi.get("/api/v1/ai/conversations")).json()["data"]
    assert [c["id"] for c in listing] == [conv_id]
    assert listing[0]["context_type"] == "global"

    r = await ravi.put(
        "/api/v1/ai/feedback",
        json={"target_type": "ai_message", "target_id": message_id, "rating": -1},
    )
    assert r.status_code == 200 and r.json()["rating"] == -1
    r = await ravi.put(  # a second rating replaces the first
        "/api/v1/ai/feedback",
        json={"target_type": "ai_message", "target_id": message_id, "rating": 1, "comment": "ok"},
    )
    assert r.status_code == 200

    detail = (await ravi.get(f"/api/v1/ai/conversations/{conv_id}")).json()
    msgs = detail["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[1]["rating"] == 1 and msgs[3]["rating"] is None
    assert msgs[1]["citations"] and all(c["valid"] for c in msgs[1]["citations"])
    assert msgs[1]["steps"][0]["name"] == "semantic_search"

    # access changes after the answer: the stored citation stops being a link
    async with uow.transaction() as s:
        await tasks.delete_task(s, world.ravi, world.copy.id)
    detail = (await ravi.get(f"/api/v1/ai/conversations/{conv_id}")).json()
    by_ref = {c["ref"]: c["valid"] for c in detail["messages"][1]["citations"]}
    assert by_ref[f"[{key(world.copy)}]"] is False and by_ref[f"[{key(world.faq)}]"] is True

    ana = await as_user("ana")
    assert (await ana.get(f"/api/v1/ai/conversations/{conv_id}")).status_code == 404
    r = await ana.put(
        "/api/v1/ai/feedback",
        json={"target_type": "ai_message", "target_id": message_id, "rating": 1},
    )
    assert r.status_code == 404
    r = await ravi.put(
        "/api/v1/ai/feedback",
        json={"target_type": "ai_message", "target_id": message_id, "rating": 0},
    )
    assert r.status_code == 422
    assert (await ravi.post("/api/v1/ai/chat", json={"text": ""})).status_code == 422


async def test_ai_off_keeps_the_question_and_ends_with_an_error(
    app_factory: Any, seeded: None, uow: UnitOfWork
) -> None:
    from tests.helpers import Clients as C

    app = app_factory(ai_enabled=False)
    async with app.router.lifespan_context(app):
        clients = C(app)
        ravi = await clients("ravi")
        async with ravi.stream("POST", "/api/v1/ai/chat", json={"text": "hello"}) as r:
            events = _events("".join([chunk async for chunk in r.aiter_text()]))
        await clients.close()
    assert [t for t, _ in events] == ["conversation", "error"]
    assert events[1][1]["reason"] == "disabled"
    async with uow.transaction() as s:
        (conv,) = (await s.execute(select(AiConversation))).scalars()
    assert [m.role for m in await messages(uow, conv.id)] == ["user"]
