"""The LLM gateway (`docs/ai/ai-architecture.md` §2, ADR-0004). Every model call goes through here.

- Code names an **alias** (`fast`, `default`, `smart`; `embed` for embeddings); the model name
  comes from settings. No model ids in code.
- Before a call: AI master switch, then the workspace's monthly budget (`BudgetExceeded`).
- Timeouts, connection errors, 429s (honoring ``Retry-After``) and 5xx are retried with
  backoff up to ``MOMENTUM_LLM_MAX_RETRIES``; anything else, or running out of retries, is
  ``AIUnavailable`` so callers can degrade gracefully.
- After every call, success or not, one ``llm_calls`` row (see `ai/usage.py`). No prompt or
  response bodies are logged or stored.

One instance per app (built in the app factory's lifespan, kept on the runtime) — no module
globals, so an embedding host can run several apps side by side.
"""

from __future__ import annotations

import asyncio
import functools
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal
from typing import TypeVar

from momentum.ai.errors import AIDisabled, AIUnavailable, BudgetExceeded, TransportError
from momentum.ai.pricing import PriceTable
from momentum.ai.transport import GatewayTransport, Transport
from momentum.ai.types import (
    CHAT_ALIASES,
    RETRYABLE,
    Alias,
    ChatRequest,
    Completion,
    DoneEvent,
    EmbedRequest,
    InputType,
    Msg,
    RawCompletion,
    RerankRequest,
    StreamEvent,
    TokenEvent,
    ToolCallDeltaEvent,
    ToolChoice,
    ToolSchema,
)
from momentum.ai.usage import CallRecord, DbUsageLog, NullUsageLog, UsageLog
from momentum.core.context import Ctx
from momentum.core.settings import Settings
from momentum.core.telemetry import get_logger

T = TypeVar("T")
MAX_BACKOFF_S = 8.0
MAX_RETRY_AFTER_S = 30.0

log = get_logger("ai.llm")


class LLM:
    def __init__(
        self,
        settings: Settings,
        transport: Transport,
        usage: UsageLog,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.usage = usage
        self.prices = PriceTable.parse(settings.llm_price_table)
        self._sleep = sleep

    # --- aliases ---------------------------------------------------------------------------
    def model_for(self, alias: str) -> str:
        s = self.settings
        models = {
            "fast": s.llm_model_fast,
            "default": s.llm_model_default,
            "smart": s.llm_model_smart,
            "embed": s.llm_embed_model,
        }
        if alias not in models:
            raise ValueError(f"unknown model alias {alias!r}")
        return models[alias]

    # --- chat ------------------------------------------------------------------------------
    async def complete(
        self,
        *,
        alias: Alias,
        messages: list[Msg],
        feature: str,
        ctx: Ctx,
        tools: list[ToolSchema] | None = None,
        tool_choice: ToolChoice | None = None,
        max_tokens: int = 1500,
        temperature: float = 0.2,
        prompt_version: str | None = None,
        agent_run_id: uuid.UUID | None = None,
    ) -> Completion:
        req = self._chat_request(
            alias, messages, feature, tools, tool_choice, max_tokens, temperature
        )
        rec = _RecordBase(feature, alias, req.model, prompt_version, agent_run_id)
        await self._preflight(ctx, rec)
        started = time.monotonic()
        try:
            raw = await self._with_retries(lambda: self.transport.complete(req))
        except TransportError as e:
            raise await self._failed(ctx, rec, started, e) from e
        return await self._succeeded(ctx, rec, started, raw)

    async def stream(
        self,
        *,
        alias: Alias,
        messages: list[Msg],
        feature: str,
        ctx: Ctx,
        tools: list[ToolSchema] | None = None,
        tool_choice: ToolChoice | None = None,
        max_tokens: int = 1500,
        temperature: float = 0.2,
        prompt_version: str | None = None,
        agent_run_id: uuid.UUID | None = None,
        allow_tool_fallback: bool = True,
    ) -> AsyncIterator[StreamEvent]:
        """Token and tool-call-delta events, then one ``DoneEvent`` with the full completion.

        With tools and ``MOMENTUM_LLM_SUPPORTS_STREAMING_TOOLS=false`` the step runs
        non-streaming and its result is replayed as events (same shape for the caller).
        ``llm-check`` passes ``allow_tool_fallback=False`` to probe real streaming.
        """
        req = self._chat_request(
            alias, messages, feature, tools, tool_choice, max_tokens, temperature
        )
        rec = _RecordBase(feature, alias, req.model, prompt_version, agent_run_id)
        await self._preflight(ctx, rec)
        started = time.monotonic()
        if tools and allow_tool_fallback and not self.settings.llm_supports_streaming_tools:
            try:
                raw = await self._with_retries(lambda: self.transport.complete(req))
            except TransportError as e:
                raise await self._failed(ctx, rec, started, e) from e
            done = await self._succeeded(ctx, rec, started, raw)
            if done.text:
                yield TokenEvent(done.text)
            for i, call in enumerate(done.tool_calls):
                yield ToolCallDeltaEvent(i, call.id, call.name, call.arguments)
            yield DoneEvent(done)
            return

        attempt = 0
        while True:
            emitted = False
            try:
                async for ev in self.transport.stream(req):
                    if isinstance(ev, RawCompletion):
                        yield DoneEvent(await self._succeeded(ctx, rec, started, ev))
                        return
                    emitted = True
                    yield ev
                raise TransportError("bad_response", "stream ended without a final result")
            except TransportError as e:
                # Retrying after output reached the caller would duplicate it: fail instead.
                if emitted or not self._should_retry(e, attempt):
                    raise await self._failed(ctx, rec, started, e) from e
                await self._sleep(self._backoff(e, attempt))
                attempt += 1

    # --- embeddings ------------------------------------------------------------------------
    async def embed(
        self,
        texts: list[str],
        *,
        input_type: InputType,
        feature: str,
        ctx: Ctx,
    ) -> list[list[float]]:
        """Vectors for ``texts`` in order, sent in batches of ``MOMENTUM_LLM_EMBED_BATCH``.

        Use ``search_document`` for content being indexed and ``search_query`` for the user's
        query: Cohere v3 embeds them differently, and mixing them up quietly hurts recall.
        """
        model = self.model_for("embed")
        rec = _RecordBase(feature, "embed", model, None, None)
        await self._preflight(ctx, rec)
        if not texts:
            return []
        started = time.monotonic()
        vectors: list[list[float]] = []
        tokens = 0
        resolved = model
        size = self.settings.llm_embed_batch
        for i in range(0, len(texts), size):
            req = EmbedRequest(feature, model, texts[i : i + size], input_type)
            try:
                raw = await self._with_retries(functools.partial(self.transport.embed, req))
            except TransportError as e:
                raise await self._failed(ctx, rec, started, e) from e
            vectors.extend(raw.vectors)
            tokens += raw.tokens_in
            resolved = raw.model
        await self.usage.record(
            ctx,
            CallRecord(
                feature=feature,
                alias="embed",
                model=resolved,
                status="ok",
                tokens_in=tokens,
                cost_usd=self.prices.cost(model, tokens, 0),
                latency_ms=_ms_since(started),
            ),
        )
        return vectors

    # --- rerank ----------------------------------------------------------------------------
    async def rerank(
        self, query: str, documents: list[str], *, top_n: int, feature: str, ctx: Ctx
    ) -> list[tuple[int, float]]:
        """``(index, score)`` of the ``top_n`` most relevant documents, best first (S3.1.4's
        optional retrieval step; model from ``MOMENTUM_LLM_RERANK_MODEL``)."""
        model = self.settings.llm_rerank_model
        rec = _RecordBase(feature, "rerank", model, None, None)
        await self._preflight(ctx, rec)
        if not documents:
            return []
        req = RerankRequest(feature, model, query, documents, min(top_n, len(documents)))
        started = time.monotonic()
        try:
            raw = await self._with_retries(functools.partial(self.transport.rerank, req))
        except TransportError as e:
            raise await self._failed(ctx, rec, started, e) from e
        await self.usage.record(
            ctx,
            rec.to_record(
                "ok",
                model=raw.model,
                cost_usd=self.prices.cost(model, raw.units * 1_000_000, 0),
                latency_ms=_ms_since(started),
            ),
        )
        return raw.ranking

    async def aclose(self) -> None:
        await self.transport.aclose()

    # --- internals -------------------------------------------------------------------------
    def _chat_request(
        self,
        alias: str,
        messages: list[Msg],
        feature: str,
        tools: list[ToolSchema] | None,
        tool_choice: ToolChoice | None,
        max_tokens: int,
        temperature: float,
    ) -> ChatRequest:
        if alias not in CHAT_ALIASES:
            raise ValueError(f"{alias!r} is not a chat alias (use one of {CHAT_ALIASES})")
        return ChatRequest(
            feature=feature,
            alias=alias,
            model=self.model_for(alias),
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def _preflight(self, ctx: Ctx, rec: _RecordBase) -> None:
        if not self.settings.ai_enabled:
            raise AIDisabled()
        try:
            await self.usage.check_budget(ctx)
        except BudgetExceeded:
            await self.usage.record(ctx, rec.to_record("budget_exceeded"))
            raise

    def _should_retry(self, e: TransportError, attempt: int) -> bool:
        return e.kind in RETRYABLE and attempt < self.settings.llm_max_retries

    def _backoff(self, e: TransportError, attempt: int) -> float:
        if e.retry_after is not None:
            return min(max(e.retry_after, 0.0), MAX_RETRY_AFTER_S)
        return float(min(0.5 * (2**attempt), MAX_BACKOFF_S))

    async def _with_retries(self, call: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        while True:
            try:
                return await call()
            except TransportError as e:
                if not self._should_retry(e, attempt):
                    raise
                log.warning("llm_retry", kind=e.kind, attempt=attempt + 1)
                await self._sleep(self._backoff(e, attempt))
                attempt += 1

    async def _succeeded(
        self, ctx: Ctx, rec: _RecordBase, started: float, raw: RawCompletion
    ) -> Completion:
        latency = _ms_since(started)
        cost = self.prices.cost(rec.model, raw.tokens_in, raw.tokens_out)
        await self.usage.record(
            ctx,
            rec.to_record(
                "ok",
                model=raw.model,
                tokens_in=raw.tokens_in,
                tokens_out=raw.tokens_out,
                cost_usd=cost,
                latency_ms=latency,
            ),
        )
        log.debug("llm_call", feature=rec.feature, alias=rec.alias, latency_ms=latency)
        return Completion(
            text=raw.text,
            tool_calls=raw.tool_calls,
            finish_reason=raw.finish_reason,
            alias=rec.alias,  # type: ignore[arg-type]
            model=raw.model,
            tokens_in=raw.tokens_in,
            tokens_out=raw.tokens_out,
            cost_usd=cost,
            latency_ms=latency,
            usage_reported=raw.usage_reported,
        )

    async def _failed(
        self, ctx: Ctx, rec: _RecordBase, started: float, e: TransportError
    ) -> AIUnavailable:
        await self.usage.record(
            ctx, rec.to_record("error", error_code=e.kind, latency_ms=_ms_since(started))
        )
        log.warning("llm_call_failed", feature=rec.feature, alias=rec.alias, kind=e.kind)
        return AIUnavailable(reason=e.kind, internal_detail=str(e))


class _RecordBase:
    def __init__(
        self,
        feature: str,
        alias: str,
        model: str,
        prompt_version: str | None,
        agent_run_id: uuid.UUID | None,
    ) -> None:
        self.feature = feature
        self.alias = alias
        self.model = model
        self.prompt_version = prompt_version
        self.agent_run_id = agent_run_id

    def to_record(
        self,
        status: str,
        *,
        model: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: Decimal = Decimal(0),
        latency_ms: int = 0,
        error_code: str | None = None,
    ) -> CallRecord:
        return CallRecord(
            feature=self.feature,
            alias=self.alias,
            model=model or self.model,
            status=status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            error_code=error_code,
            prompt_version=self.prompt_version,
            agent_run_id=self.agent_run_id,
        )


def _ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def build_transport(settings: Settings) -> Transport:
    from momentum.ai.mock import MockTransport, RecordingTransport

    if settings.llm_mode == "mock":
        return MockTransport(settings)
    if settings.llm_mode == "record":
        return RecordingTransport(settings, GatewayTransport(settings))
    return GatewayTransport(settings)


def build_llm(settings: Settings, usage: UsageLog | None = None) -> LLM:
    return LLM(settings, build_transport(settings), usage or NullUsageLog())


__all__ = ["LLM", "DbUsageLog", "NullUsageLog", "build_llm", "build_transport"]
