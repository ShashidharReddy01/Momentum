"""S3.1.1: the LLM gateway (`momentum/ai/llm.py`), its transports, usage logging and llm-check.

Gateway-mode tests run the real OpenAI SDK against an in-process fake OpenAI-compatible server
(an httpx2 MockTransport), so request shapes, SSE parsing, headers and error mapping are all
exercised without network access.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai.check import recommendations, render, run_llm_check
from momentum.ai.errors import AIDisabled, AIUnavailable, BudgetExceeded
from momentum.ai.llm import LLM, build_llm
from momentum.ai.mock import MockTransport, RecordingTransport, mock_embedding, request_key
from momentum.ai.models import LlmCall
from momentum.ai.transport import GatewayTransport
from momentum.ai.types import DoneEvent, TokenEvent, ToolCallAccumulator, ToolCallDeltaEvent
from momentum.ai.usage import DbUsageLog, NullUsageLog, UsageLog
from momentum.core.context import Actor, Ctx
from momentum.core.db import UnitOfWork
from momentum.core.settings import Settings
from tests.conftest import make_settings
from tests.helpers import ctx_for

ADD_TOOL = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers.",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        },
    },
}


def system_ctx(settings: Settings) -> Ctx:
    return Ctx(actor=Actor(id=None, workspace_id=uuid.UUID(int=0)), settings=settings)


# --- a fake OpenAI-compatible gateway -------------------------------------------------------


def _chat_json(model: str, text: str = "", tool_calls: list[dict[str, Any]] | None = None) -> Any:
    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
            }
            for i, tc in enumerate(tool_calls)
        ]
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
    }


def _sse(chunks: list[dict[str, Any]]) -> bytes:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return body.encode()


def _chunk(model: str, delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {
        "id": "cmpl-1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


class FakeGateway:
    """Behaves like LiteLLM/Portkey for the endpoints Momentum uses."""

    def __init__(self, *, streaming_tools: bool = True, dim: int = 1024) -> None:
        self.requests: list[httpx2.Request] = []
        self.failures: list[httpx2.Response] = []  # returned (in order) before real answers
        self.streaming_tools = streaming_tools
        self.dim = dim

    def body(self, i: int) -> dict[str, Any]:
        return json.loads(self.requests[i].content)  # type: ignore[no-any-return]

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.failures:
            return self.failures.pop(0)
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            base = 1.0 if body.get("input_type") == "search_document" else 0.5
            data = [
                {"object": "embedding", "index": i, "embedding": [base + i] * self.dim}
                for i, _ in enumerate(body["input"])
            ]
            usage = {"prompt_tokens": 3 * len(body["input"]), "total_tokens": 0}
            return httpx2.Response(
                200, json={"object": "list", "data": data, "model": body["model"], "usage": usage}
            )
        model = body["model"]
        wants_tool = bool(body.get("tools"))
        if body.get("stream"):
            if wants_tool and not self.streaming_tools:
                return httpx2.Response(400, json={"error": {"message": "tools+stream unsupported"}})
            if wants_tool:
                chunks = [
                    _chunk(
                        model,
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_0",
                                    "type": "function",
                                    "function": {"name": "add", "arguments": '{"a": 2,'},
                                }
                            ]
                        },
                    ),
                    _chunk(
                        model,
                        {"tool_calls": [{"index": 0, "function": {"arguments": ' "b": 3}'}}]},
                        "tool_calls",
                    ),
                ]
            else:
                chunks = [_chunk(model, {"content": w}) for w in ("one ", "two ", "three")]
                chunks[-1]["choices"][0]["finish_reason"] = "stop"
            chunks.append(
                {
                    "id": "cmpl-1",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model,
                    "choices": [],
                    "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
                }
            )
            return httpx2.Response(
                200, content=_sse(chunks), headers={"content-type": "text/event-stream"}
            )
        if wants_tool:
            forced = (body.get("tool_choice") or {}).get("function", {}).get("name")
            if forced == "update_task":  # llm-check's catalog-schema probe
                call = {
                    "name": "update_task",
                    "arguments": {"task": "T-12", "due_on": "2026-10-09"},
                }
            else:
                call = {"name": "add", "arguments": {"a": 2, "b": 3}}
            return httpx2.Response(200, json=_chat_json(model, tool_calls=[call]))
        return httpx2.Response(200, json=_chat_json(model, text="pong"))


def gateway_llm(
    settings: Settings,
    fake: FakeGateway,
    usage: UsageLog | None = None,
    sleeps: list[float] | None = None,
) -> LLM:
    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    transport = GatewayTransport(
        settings, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handler))
    )
    return LLM(settings, transport, usage or NullUsageLog(), sleep=sleep)


def gw_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "llm_mode": "gateway",
        "llm_base_url": "http://gateway.test/v1",
        "llm_api_key": "sk-test-key",
        "llm_model_default": "provider/chat-default",
        "llm_model_fast": "provider/chat-fast",
        "llm_model_smart": "provider/chat-smart",
        "llm_embed_model": "provider/embed",
    }
    base.update(overrides)
    return make_settings(**base)


# --- aliases, switches -----------------------------------------------------------------------


async def test_aliases_resolve_to_configured_models() -> None:
    s = gw_settings()
    llm = gateway_llm(s, FakeGateway())
    assert llm.model_for("fast") == "provider/chat-fast"
    assert llm.model_for("default") == "provider/chat-default"
    assert llm.model_for("smart") == "provider/chat-smart"
    assert llm.model_for("embed") == "provider/embed"
    with pytest.raises(ValueError):
        llm.model_for("gpt-4o")
    with pytest.raises(ValueError):  # embed is not a chat alias
        await llm.complete(
            alias="embed",  # type: ignore[arg-type]
            messages=[{"role": "user", "content": "x"}],
            feature="t",
            ctx=system_ctx(s),
        )


async def test_ai_disabled_refuses_calls_without_touching_the_gateway() -> None:
    s = gw_settings(ai_enabled=False)
    fake = FakeGateway()
    llm = gateway_llm(s, fake)
    with pytest.raises(AIDisabled):
        await llm.complete(
            alias="default",
            messages=[{"role": "user", "content": "x"}],
            feature="t",
            ctx=system_ctx(s),
        )
    assert fake.requests == []


def test_production_never_silently_uses_mock_ai() -> None:
    with pytest.raises(ValueError, match="LLM_MODE"):
        make_settings(env="production", auth_mode="easyauth", secret_key="x" * 40, llm_mode="mock")
    make_settings(env="production", auth_mode="easyauth", secret_key="x" * 40, llm_mode="gateway")
    make_settings(
        env="production",
        auth_mode="easyauth",
        secret_key="x" * 40,
        llm_mode="mock",
        ai_enabled=False,
    )


def test_extra_headers_setting_must_be_a_json_object_of_strings() -> None:
    with pytest.raises(ValueError, match="EXTRA_HEADERS"):
        make_settings(llm_extra_headers="not json")
    with pytest.raises(ValueError, match="EXTRA_HEADERS"):
        make_settings(llm_extra_headers='{"x-n": 1}')


# --- gateway mode ----------------------------------------------------------------------------


async def test_gateway_complete_sends_resolved_model_tools_and_bearer_key() -> None:
    s = gw_settings()
    fake = FakeGateway()
    llm = gateway_llm(s, fake)
    c = await llm.complete(
        alias="fast",
        messages=[{"role": "user", "content": "add 2 and 3"}],
        tools=[ADD_TOOL],
        tool_choice={"type": "function", "function": {"name": "add"}},
        feature="t",
        ctx=system_ctx(s),
    )
    assert c.tool_calls[0].name == "add"
    assert c.tool_calls[0].args() == {"a": 2, "b": 3}
    assert (c.tokens_in, c.tokens_out, c.alias) == (12, 5, "fast")
    req = fake.requests[0]
    assert req.url == "http://gateway.test/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-test-key"
    body = fake.body(0)
    assert body["model"] == "provider/chat-fast"
    assert body["tools"][0]["function"]["name"] == "add"
    assert body["tool_choice"] == {"type": "function", "function": {"name": "add"}}


async def test_gateway_key_can_go_in_a_custom_header_with_extra_headers() -> None:
    """Portkey-style gateways take their key in their own header plus routing headers."""
    s = gw_settings(
        llm_api_key_header="x-gateway-api-key",
        llm_extra_headers='{"x-gateway-provider": "@bedrock-config"}',
    )
    fake = FakeGateway()
    await gateway_llm(s, fake).complete(
        alias="default",
        messages=[{"role": "user", "content": "hi"}],
        feature="t",
        ctx=system_ctx(s),
    )
    headers = fake.requests[0].headers
    assert headers["x-gateway-api-key"] == "sk-test-key"
    assert headers["x-gateway-provider"] == "@bedrock-config"


async def test_gateway_embeddings_batch_in_order_and_pass_input_type() -> None:
    s = gw_settings(llm_embed_batch=2, llm_embed_dim=4)
    fake = FakeGateway(dim=4)
    vecs = await gateway_llm(s, fake).embed(
        ["a", "b", "c", "d", "e"], input_type="search_document", feature="embed", ctx=system_ctx(s)
    )
    assert len(fake.requests) == 3
    assert [fake.body(i)["input"] for i in range(3)] == [["a", "b"], ["c", "d"], ["e"]]
    for i in range(3):
        assert fake.body(i)["input_type"] == "search_document"
        assert fake.body(i)["encoding_format"] == "float"
        assert fake.body(i)["model"] == "provider/embed"
    # Order preserved across batches (each batch's vectors are base + position in batch).
    assert [v[0] for v in vecs] == [1.0, 2.0, 1.0, 2.0, 1.0]


async def test_rate_limit_is_retried_honoring_retry_after() -> None:
    s = gw_settings(llm_max_retries=2)
    fake = FakeGateway()
    fake.failures = [httpx2.Response(429, headers={"retry-after": "3"}, json={"error": {}})]
    sleeps: list[float] = []
    c = await gateway_llm(s, fake, sleeps=sleeps).complete(
        alias="default",
        messages=[{"role": "user", "content": "hi"}],
        feature="t",
        ctx=system_ctx(s),
    )
    assert c.text == "pong"
    assert sleeps == [3.0]
    assert len(fake.requests) == 2


async def test_server_errors_retry_with_backoff_then_fail_as_unavailable(
    seeded: None, uow: UnitOfWork, settings: Settings, session_factory: Any
) -> None:
    s = gw_settings(llm_max_retries=2)
    ctx = await ctx_for(uow, s, "ravi")
    fake = FakeGateway()
    fake.failures = [httpx2.Response(503, json={"error": {"message": "overloaded"}})] * 3
    sleeps: list[float] = []
    llm = gateway_llm(s, fake, usage=DbUsageLog(session_factory, 0), sleeps=sleeps)
    with pytest.raises(AIUnavailable) as err:
        await llm.complete(
            alias="default", messages=[{"role": "user", "content": "hi"}], feature="chat", ctx=ctx
        )
    assert err.value.reason == "server_error"
    assert err.value.status == 503
    assert len(fake.requests) == 3  # 1 + MOMENTUM_LLM_MAX_RETRIES
    assert sleeps == [0.5, 1.0]
    async with session_factory() as session:
        row = (await session.scalars(select(LlmCall))).one()
    assert (row.status, row.error_code, row.feature) == ("error", "server_error", "chat")


async def test_bad_request_is_not_retried() -> None:
    s = gw_settings(llm_max_retries=2)
    fake = FakeGateway()
    fake.failures = [httpx2.Response(400, json={"error": {"message": "bad tool schema"}})]
    with pytest.raises(AIUnavailable) as err:
        await gateway_llm(s, fake).complete(
            alias="default",
            messages=[{"role": "user", "content": "x"}],
            feature="t",
            ctx=system_ctx(s),
        )
    assert err.value.reason == "bad_request"
    assert len(fake.requests) == 1
    assert "bad tool schema" in err.value.internal_detail


async def test_streaming_text_then_done_with_usage() -> None:
    s = gw_settings()
    fake = FakeGateway()
    events = [
        ev
        async for ev in gateway_llm(s, fake).stream(
            alias="default",
            messages=[{"role": "user", "content": "count"}],
            feature="chat",
            ctx=system_ctx(s),
        )
    ]
    tokens = [ev.text for ev in events if isinstance(ev, TokenEvent)]
    assert tokens == ["one ", "two ", "three"]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.completion.text == "one two three"
    assert (done.completion.tokens_in, done.completion.tokens_out) == (9, 4)
    assert fake.body(0)["stream"] is True
    assert fake.body(0)["stream_options"] == {"include_usage": True}


async def test_streaming_tool_call_deltas_assemble_into_a_call() -> None:
    s = gw_settings()
    fake = FakeGateway()
    acc = ToolCallAccumulator()
    done = None
    async for ev in gateway_llm(s, fake).stream(
        alias="default",
        messages=[{"role": "user", "content": "add"}],
        tools=[ADD_TOOL],
        feature="t",
        ctx=system_ctx(s),
    ):
        if isinstance(ev, ToolCallDeltaEvent):
            acc.add(ev)
        elif isinstance(ev, DoneEvent):
            done = ev.completion
    assert acc.calls()[0].args() == {"a": 2, "b": 3}
    assert done is not None and done.tool_calls[0].args() == {"a": 2, "b": 3}


async def test_stream_retries_only_before_anything_was_emitted() -> None:
    s = gw_settings(llm_max_retries=1)
    fake = FakeGateway()
    fake.failures = [httpx2.Response(502, json={"error": {}})]
    events = [
        ev
        async for ev in gateway_llm(s, fake).stream(
            alias="default",
            messages=[{"role": "user", "content": "x"}],
            feature="t",
            ctx=system_ctx(s),
        )
    ]
    assert isinstance(events[-1], DoneEvent)
    assert len(fake.requests) == 2


class _DropsAfterFirstChunk(httpx2.AsyncByteStream):
    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield _sse([_chunk("m", {"content": "partial "})]).split(b"data: [DONE]")[0]
        raise httpx2.ReadError("connection reset by peer")


async def test_stream_that_drops_after_output_fails_instead_of_retrying(
    seeded: None, uow: UnitOfWork, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Retrying after tokens reached the caller would duplicate them, so it must fail."""
    s = gw_settings(llm_max_retries=2)
    ctx = await ctx_for(uow, s, "ravi")
    fake = FakeGateway()
    fake.failures = [
        httpx2.Response(
            200, stream=_DropsAfterFirstChunk(), headers={"content-type": "text/event-stream"}
        )
    ]
    llm = gateway_llm(s, fake, usage=DbUsageLog(session_factory, 0))
    seen: list[str] = []
    with pytest.raises(AIUnavailable) as err:
        async for ev in llm.stream(
            alias="default", messages=[{"role": "user", "content": "x"}], feature="chat", ctx=ctx
        ):
            if isinstance(ev, TokenEvent):
                seen.append(ev.text)
    assert seen == ["partial "]
    assert err.value.reason == "connection"
    assert len(fake.requests) == 1
    async with session_factory() as session:
        row = (await session.scalars(select(LlmCall))).one()
    assert (row.status, row.error_code) == ("error", "connection")


async def test_without_streaming_tool_support_tool_steps_run_non_streaming() -> None:
    s = gw_settings(llm_supports_streaming_tools=False)
    fake = FakeGateway(streaming_tools=False)
    events = [
        ev
        async for ev in gateway_llm(s, fake).stream(
            alias="default",
            messages=[{"role": "user", "content": "add"}],
            tools=[ADD_TOOL],
            feature="t",
            ctx=system_ctx(s),
        )
    ]
    assert "stream" not in fake.body(0)
    deltas = [ev for ev in events if isinstance(ev, ToolCallDeltaEvent)]
    assert deltas and deltas[0].name == "add"
    assert isinstance(events[-1], DoneEvent)


# --- usage logging and budget ----------------------------------------------------------------


async def test_every_call_logs_usage_and_cost_but_never_content(
    seeded: None, uow: UnitOfWork, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    s = gw_settings(
        llm_price_table='{"provider/chat-default": {"in_per_mtok": 3, "out_per_mtok": 15}}'
    )
    ctx = await ctx_for(uow, s, "ravi")
    llm = gateway_llm(s, FakeGateway(), usage=DbUsageLog(session_factory, 0))
    c = await llm.complete(
        alias="default",
        messages=[{"role": "user", "content": "SECRET-PROMPT-TEXT"}],
        feature="summarize",
        ctx=ctx,
        prompt_version="v2",
    )
    # 12 in * $3/M + 5 out * $15/M
    assert c.cost_usd == Decimal("0.000111")
    await llm.embed(["x"], input_type="search_query", feature="embed", ctx=ctx)
    async with session_factory() as session:
        rows = (await session.scalars(select(LlmCall).order_by(LlmCall.created_at))).all()
    chat, emb = rows
    assert chat.feature == "summarize" and chat.alias == "default"
    assert chat.model == "provider/chat-default" and chat.prompt_version == "v2"
    assert (chat.tokens_in, chat.tokens_out, chat.status) == (12, 5, "ok")
    assert chat.cost_usd == Decimal("0.000111")
    assert chat.user_id == ctx.actor.id and chat.workspace_id == ctx.workspace_id
    assert chat.latency_ms >= 0
    assert (emb.alias, emb.tokens_in, emb.status) == ("embed", 3, "ok")
    stored = " ".join(str(getattr(chat, col.key)) for col in LlmCall.__table__.columns)
    assert "SECRET-PROMPT-TEXT" not in stored


async def test_budget_is_checked_before_calling_and_resets_monthly(
    seeded: None, uow: UnitOfWork, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    s = gw_settings(ai_monthly_budget_usd=5)
    ctx = await ctx_for(uow, s, "ravi")
    usage = DbUsageLog(session_factory, 5)
    fake = FakeGateway()
    llm = gateway_llm(s, fake, usage=usage)
    last_month = datetime.now(UTC).replace(day=1) - timedelta(days=2)
    async with session_factory() as session, session.begin():
        session.add(
            LlmCall(
                workspace_id=ctx.workspace_id,
                feature="chat",
                alias="default",
                model="m",
                status="ok",
                cost_usd=Decimal(50),
                created_at=last_month,
            )
        )
    # Last month's spend doesn't count.
    await llm.complete(
        alias="default", messages=[{"role": "user", "content": "x"}], feature="chat", ctx=ctx
    )
    async with session_factory() as session, session.begin():
        session.add(
            LlmCall(
                workspace_id=ctx.workspace_id,
                feature="chat",
                alias="default",
                model="m",
                status="ok",
                cost_usd=Decimal(5),
            )
        )
    calls_before = len(fake.requests)
    with pytest.raises(BudgetExceeded):
        await llm.complete(
            alias="default", messages=[{"role": "user", "content": "x"}], feature="chat", ctx=ctx
        )
    assert len(fake.requests) == calls_before  # the gateway was never called
    async with session_factory() as session:
        statuses = (await session.scalars(select(LlmCall.status))).all()
    assert "budget_exceeded" in statuses


# --- mock and record modes -------------------------------------------------------------------


def _write(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.write_text(yaml.safe_dump(data), encoding="utf-8")


async def test_mock_mode_matches_fixtures_then_falls_back(tmp_path: Path) -> None:
    msgs = [{"role": "system", "content": "today is X"}, {"role": "user", "content": "Hello there"}]
    key = request_key(msgs, None)
    # The key ignores system messages (they carry today's date).
    assert key == request_key([msgs[1]], None)
    _write(
        tmp_path / "summarize.yaml",
        {
            "responses": [
                {"match": {"key": key}, "text": "by key"},
                {
                    "match": {"contains": "catch me up"},
                    "tool_calls": [{"name": "t", "arguments": {"x": 1}}],
                },
            ],
            "default": {"text": "feature default"},
        },
    )
    _write(tmp_path / "_default.yaml", {"default": {"text": "(mock) global"}})
    s = make_settings(llm_fixtures_dir=str(tmp_path))
    llm = build_llm(s)
    ctx = system_ctx(s)

    async def ask(feature: str, text: str, messages: list[dict[str, Any]] | None = None) -> Any:
        return await llm.complete(
            alias="fast",
            messages=messages or [{"role": "user", "content": text}],
            feature=feature,
            ctx=ctx,
        )

    assert (await ask("summarize", "", msgs)).text == "by key"
    c = await ask("summarize", "Please CATCH ME UP on this")
    assert c.tool_calls[0].name == "t" and c.tool_calls[0].args() == {"x": 1}
    assert (await ask("summarize", "anything")).text == "feature default"
    assert (await ask("other_feature", "anything")).text == "(mock) global"
    c = await ask("summarize", "anything")
    assert c.model == "mock/fast" and c.tokens_in > 0 and c.cost_usd == 0


async def test_packaged_fallback_is_visibly_mock() -> None:
    s = make_settings()
    c = await build_llm(s).complete(
        alias="default",
        messages=[{"role": "user", "content": "hi"}],
        feature="no_such_feature",
        ctx=system_ctx(s),
    )
    assert "(mock)" in c.text


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_mock_embeddings_are_deterministic_unit_vectors_with_lexical_similarity() -> None:
    doc = mock_embedding("Draft the pricing page copy", "search_document", 1024)
    assert doc == mock_embedding("Draft the pricing page copy", "search_document", 1024)
    assert len(doc) == 1024
    assert math.isclose(math.sqrt(sum(v * v for v in doc)), 1.0, rel_tol=1e-9)
    query = mock_embedding("pricing copy drafts", "search_query", 1024)
    unrelated = mock_embedding("fix the login bug on mobile", "search_query", 1024)
    assert _cos(query, doc) > _cos(unrelated, doc)
    assert mock_embedding("x", "search_query", 8) != mock_embedding("x", "search_document", 8)


async def test_record_mode_saves_fixtures_that_mock_mode_replays(tmp_path: Path) -> None:
    s = gw_settings(llm_mode="record", llm_fixtures_dir=str(tmp_path))
    fake = FakeGateway()
    inner = GatewayTransport(
        s, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handler))
    )
    recorder = LLM(s, RecordingTransport(s, inner), NullUsageLog())
    msgs = [{"role": "user", "content": "add please"}]
    real = await recorder.complete(
        alias="default", messages=msgs, tools=[ADD_TOOL], feature="command", ctx=system_ctx(s)
    )
    assert (tmp_path / "command.yaml").is_file()

    mock_settings = make_settings(llm_fixtures_dir=str(tmp_path))
    replay = await LLM(mock_settings, MockTransport(mock_settings), NullUsageLog()).complete(
        alias="default",
        messages=msgs,
        tools=[ADD_TOOL],
        feature="command",
        ctx=system_ctx(mock_settings),
    )
    assert replay.tool_calls[0].name == real.tool_calls[0].name
    assert replay.tool_calls[0].args() == real.tool_calls[0].args()


# --- llm-check -------------------------------------------------------------------------------


async def test_llm_check_passes_in_mock_mode() -> None:
    results = await run_llm_check(build_llm(make_settings()))
    assert {r.name for r in results} >= {
        "basic chat (default)",
        "basic chat (fast)",
        "basic chat (smart)",
        "tool calling",
        "streaming",
        "streaming with tool calls",
        "tool schemas (catalog)",
        "embeddings (search_document)",
        "embeddings (search_query)",
    }
    assert all(r.status == "pass" for r in results), render(results, [], header="")


async def test_llm_check_against_a_gateway_recommends_disabling_streaming_tools() -> None:
    s = gw_settings(llm_max_retries=0)
    results = await run_llm_check(gateway_llm(s, FakeGateway(streaming_tools=False)))
    by_name = {r.name: r for r in results}
    assert by_name["tool calling"].status == "pass"
    assert by_name["tool schemas (catalog)"].status == "pass"
    assert by_name["streaming"].status == "pass"
    assert by_name["streaming with tool calls"].status == "fail"
    assert by_name["embeddings (search_query)"].status == "pass"
    recs = recommendations(results)
    assert any("MOMENTUM_LLM_SUPPORTS_STREAMING_TOOLS=false" in r for r in recs)
    table = render(results, recs, header="Mode: gateway")
    assert "FAIL" in table and "PASS" in table and "Recommendation:" in table


async def test_llm_check_flags_a_wrong_embedding_dimension() -> None:
    s = gw_settings(llm_max_retries=0, llm_embed_dim=1024)
    results = await run_llm_check(gateway_llm(s, FakeGateway(dim=768)))
    emb = [r for r in results if r.name.startswith("embeddings")]
    assert all(r.status == "fail" and "768" in r.detail for r in emb)
    assert any("dimension" in r.lower() for r in recommendations(results))


def test_llm_check_cli_prints_a_table(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from momentum.cli import cli

    monkeypatch.setenv("MOMENTUM_LLM_MODE", "mock")
    monkeypatch.setenv("MOMENTUM_LLM_API_KEY", "sk-should-never-be-printed")
    result = CliRunner().invoke(cli, ["llm-check"])
    assert result.exit_code == 0, result.output
    assert "Mode: mock" in result.output
    assert "streaming with tool calls" in result.output
    assert "sk-should-never-be-printed" not in result.output


async def test_app_runtime_carries_one_gateway(app_factory: Callable[..., Any]) -> None:
    app = app_factory()
    async with app.router.lifespan_context(app):
        llm = app.state.momentum.llm
        assert isinstance(llm, LLM)
        assert isinstance(llm.usage, DbUsageLog)
