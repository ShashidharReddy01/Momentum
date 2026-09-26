"""The real transport: an OpenAI-compatible gateway (LiteLLM, Portkey, …) via the OpenAI SDK
(ADR-0004). SDK exceptions never leave this module — they become ``TransportError`` kinds, and
the gateway (`ai/llm.py`) owns retries, so the SDK's own retries are turned off.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx2
import openai

from momentum.ai.errors import TransportError
from momentum.ai.types import (
    ChatRequest,
    EmbedRequest,
    FailureKind,
    RawCompletion,
    RawEmbedding,
    TokenEvent,
    ToolCall,
    ToolCallAccumulator,
    ToolCallDeltaEvent,
    TransportEvent,
)
from momentum.core.settings import Settings


class Transport(Protocol):
    async def complete(self, req: ChatRequest) -> RawCompletion: ...

    def stream(self, req: ChatRequest) -> AsyncIterator[TransportEvent]:
        """Yields token / tool-call-delta events, then exactly one final ``RawCompletion``."""
        ...

    async def embed(self, req: EmbedRequest) -> RawEmbedding: ...

    async def aclose(self) -> None: ...


def _retry_after(e: openai.APIStatusError) -> float | None:
    raw = e.response.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _map_error(e: Exception) -> TransportError:
    kind: FailureKind
    retry_after = None
    if isinstance(e, openai.APITimeoutError | httpx2.TimeoutException):
        kind = "timeout"
    elif isinstance(e, httpx2.TransportError):
        # Mid-stream drops surface as raw transport errors while iterating the SSE body.
        kind = "connection"
    elif isinstance(e, openai.APIConnectionError):
        kind = "connection"
    elif isinstance(e, openai.RateLimitError):
        kind, retry_after = "rate_limited", _retry_after(e)
    elif isinstance(e, openai.AuthenticationError | openai.PermissionDeniedError):
        kind = "auth"
    elif isinstance(e, openai.APIStatusError):
        kind = "server_error" if e.status_code >= 500 else "bad_request"
    else:
        kind = "bad_response"
    # Status + a short excerpt only: gateway error bodies can echo request content.
    return TransportError(kind, f"{type(e).__name__}: {str(e)[:300]}", retry_after=retry_after)


def _chat_kwargs(req: ChatRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": req.model,
        "messages": req.messages,
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
    }
    if req.tools:
        kwargs["tools"] = req.tools
        if req.tool_choice is not None:
            kwargs["tool_choice"] = req.tool_choice
    return kwargs


class GatewayTransport:
    def __init__(self, settings: Settings, *, http_client: httpx2.AsyncClient | None = None):
        headers = dict(settings.llm_headers)
        key = settings.llm_api_key
        if key and settings.llm_api_key_header.lower() != "authorization":
            headers[settings.llm_api_key_header] = key
        self._client = openai.AsyncOpenAI(
            api_key=key or "none",  # the SDK insists on a value; keyless local gateways exist
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_s,
            max_retries=0,
            default_headers=headers,
            http_client=http_client,
        )

    async def complete(self, req: ChatRequest) -> RawCompletion:
        try:
            resp = await self._client.chat.completions.create(**_chat_kwargs(req))
        except openai.OpenAIError as e:
            raise _map_error(e) from e
        if not resp.choices:
            raise TransportError("bad_response", "gateway returned no choices")
        choice = resp.choices[0]
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "")
            for tc in (choice.message.tool_calls or [])
            if tc.type == "function"
        ]
        usage = resp.usage
        return RawCompletion(
            text=choice.message.content or "",
            tool_calls=calls,
            finish_reason=choice.finish_reason,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
            model=resp.model or req.model,
            usage_reported=usage is not None,
        )

    async def stream(self, req: ChatRequest) -> AsyncIterator[TransportEvent]:
        text: list[str] = []
        acc = ToolCallAccumulator()
        finish: str | None = None
        tokens_in = tokens_out = 0
        usage_reported = False
        model = req.model
        try:
            chunks = await self._client.chat.completions.create(
                **_chat_kwargs(req), stream=True, stream_options={"include_usage": True}
            )
            async for chunk in chunks:
                model = chunk.model or model
                if chunk.usage is not None:
                    usage_reported = True
                    tokens_in = chunk.usage.prompt_tokens
                    tokens_out = chunk.usage.completion_tokens
                for choice in chunk.choices:
                    delta = choice.delta
                    if delta.content:
                        text.append(delta.content)
                        yield TokenEvent(delta.content)
                    for tc in delta.tool_calls or []:
                        ev = ToolCallDeltaEvent(
                            index=tc.index,
                            id=tc.id,
                            name=tc.function.name if tc.function else None,
                            arguments_delta=(tc.function.arguments or "") if tc.function else "",
                        )
                        acc.add(ev)
                        yield ev
                    if choice.finish_reason:
                        finish = choice.finish_reason
        except (openai.OpenAIError, httpx2.TransportError) as e:
            raise _map_error(e) from e
        yield RawCompletion(
            text="".join(text),
            tool_calls=acc.calls(),
            finish_reason=finish,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            usage_reported=usage_reported,
        )

    async def embed(self, req: EmbedRequest) -> RawEmbedding:
        try:
            resp = await self._client.embeddings.create(
                model=req.model,
                input=req.texts,
                encoding_format="float",
                # Cohere v3 needs input_type; OpenAI-compatible gateways pass unknown body
                # fields through (verified per gateway by `momentum llm-check`).
                extra_body={"input_type": req.input_type},
            )
        except openai.OpenAIError as e:
            raise _map_error(e) from e
        vectors = [list(d.embedding) for d in sorted(resp.data, key=lambda d: d.index)]
        if len(vectors) != len(req.texts):
            raise TransportError("bad_response", "embedding count does not match input count")
        return RawEmbedding(
            vectors=vectors,
            tokens_in=resp.usage.prompt_tokens if resp.usage else 0,
            model=resp.model or req.model,
        )

    async def aclose(self) -> None:
        await self._client.close()
