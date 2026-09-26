"""S3.4.4 writing help: every action's instruction reaches the model with the text as data
(line breaks kept, `<` escaped), replies are cleaned (quotes, fences), empty replies fail, and the
endpoint validates its inputs."""

from __future__ import annotations

import pytest

from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM, build_llm
from momentum.ai.mock import MockTransport
from momentum.ai.types import ChatRequest, RawCompletion
from momentum.ai.write import INSTRUCTIONS, clean, rewrite
from momentum.core.context import Ctx
from momentum.core.settings import Settings
from tests.conftest import make_settings
from tests.helpers import Clients


class Spy(MockTransport):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.requests: list[ChatRequest] = []

    def resolve(self, req: ChatRequest) -> RawCompletion:
        self.requests.append(req)
        return super().resolve(req)


def spy_llm() -> tuple[LLM, Spy]:
    settings = make_settings()
    llm = build_llm(settings)
    spy = Spy(settings)
    llm.transport = spy
    return llm, spy


@pytest.fixture
async def ctx(uow: object, settings: Settings, seeded: None) -> Ctx:
    from tests.helpers import ctx_for

    return await ctx_for(uow, settings, "ravi")  # type: ignore[arg-type]


async def test_actions_reach_the_model_with_text_as_data(ctx: Ctx) -> None:
    llm, spy = spy_llm()
    text = "Line one <b>bold</b>\n- item T-12"
    out = await rewrite(llm, ctx, action="improve", text=text)
    assert out == "(mock) " + text  # the mock echoes; `<` is restored in the reply
    system, user = spy.requests[0].messages
    assert INSTRUCTIONS["improve"] in system["content"]
    assert (
        user["content"]
        == '<data source="text">\nLine one &lt;b&gt;bold&lt;/b&gt;\n- item T-12\n</data>'
    )
    assert spy.requests[0].alias == "fast"
    await rewrite(llm, ctx, action="tone", text="x", tone="formal")
    assert "in a formal tone" in spy.requests[1].messages[0]["content"]
    await rewrite(llm, ctx, action="translate", text="x", language="Portuguese")
    assert "Translate it into Portuguese" in spy.requests[2].messages[0]["content"]
    with pytest.raises(ValueError):
        await rewrite(llm, ctx, action="translate", text="x")
    assert await rewrite(llm, ctx, action="fix_grammar", text="teh launch is delayd") == (
        "The launch is delayed."
    )


async def test_replies_are_cleaned_and_empty_ones_fail(ctx: Ctx) -> None:
    llm, _ = spy_llm()
    assert await rewrite(llm, ctx, action="improve", text="wrap it in quotes please") == (
        "Quoted answer."
    )
    with pytest.raises(AIUnavailable):
        await rewrite(llm, ctx, action="improve", text="reply with nothing")
    assert clean("```\nplain\n```") == "plain"
    assert clean("“Curly”") == "Curly"
    assert clean('"half') == '"half'
    assert clean("It's fine'") == "It's fine'"


async def test_write_endpoint(as_user: Clients) -> None:
    ravi = await as_user("ravi")
    r = await ravi.post("/api/v1/ai/write", json={"action": "shorten", "text": "Some long text"})
    assert r.status_code == 200 and r.json() == {"text": "(mock) Some long text"}
    bad = [
        {"action": "translate", "text": "x"},
        {"action": "translate", "text": "x", "language": "Français; drop table"},
        {"action": "improve", "text": ""},
        {"action": "improve", "text": "   "},
        {"action": "summarize", "text": "x"},
        {"action": "improve", "text": "x" * 8001},
    ]
    for body in bad:
        assert (await ravi.post("/api/v1/ai/write", json=body)).status_code == 422, body
