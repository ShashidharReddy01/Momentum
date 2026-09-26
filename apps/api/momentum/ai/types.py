"""Value types shared by the LLM gateway (`ai/llm.py`), its transports and its callers.

Messages and tool schemas use the OpenAI chat format as plain dicts, because that is the wire
format every OpenAI-compatible gateway (LiteLLM, Portkey, …) speaks and what the tool registry
(S3.1.2) will export; wrapping them in classes would only add a translation layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

Alias = Literal["fast", "default", "smart"]
CHAT_ALIASES: tuple[Alias, ...] = ("fast", "default", "smart")
InputType = Literal["search_document", "search_query"]

Msg = dict[str, Any]  # {"role": "system"|"user"|"assistant"|"tool", "content": ..., ...}
ToolSchema = dict[str, Any]  # {"type": "function", "function": {"name", "description", ...}}
ToolChoice = str | dict[str, Any]

# Transport failure kinds. The first four are retried by the gateway; the rest fail at once.
FailureKind = Literal[
    "timeout", "connection", "rate_limited", "server_error", "bad_request", "auth", "bad_response"
]
RETRYABLE: frozenset[str] = frozenset({"timeout", "connection", "rate_limited", "server_error"})


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text, exactly as the model produced it

    def args(self) -> dict[str, Any]:
        """Parsed arguments; raises ValueError when the model produced invalid JSON."""
        parsed = json.loads(self.arguments or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("tool arguments must be a JSON object")
        return parsed


@dataclass(frozen=True)
class ChatRequest:
    feature: str
    alias: Alias
    model: str
    messages: list[Msg]
    tools: list[ToolSchema] | None = None
    tool_choice: ToolChoice | None = None
    max_tokens: int = 1500
    temperature: float = 0.2


@dataclass(frozen=True)
class EmbedRequest:
    feature: str
    model: str
    texts: list[str]
    input_type: InputType


@dataclass(frozen=True)
class RerankRequest:
    feature: str
    model: str
    query: str
    documents: list[str]
    top_n: int


@dataclass(frozen=True)
class RawRerank:
    """``(index into documents, relevance score)``, best first."""

    ranking: list[tuple[int, float]]
    model: str
    units: int = 1  # Cohere bills rerank per "search unit" (one query over ≤100 documents)


@dataclass(frozen=True)
class RawCompletion:
    """What a transport returns for one chat call (before the gateway adds accounting)."""

    text: str
    tool_calls: list[ToolCall]
    finish_reason: str | None
    tokens_in: int
    tokens_out: int
    model: str
    usage_reported: bool = True


@dataclass(frozen=True)
class RawEmbedding:
    vectors: list[list[float]]
    tokens_in: int
    model: str


@dataclass(frozen=True)
class Completion:
    text: str
    tool_calls: list[ToolCall]
    finish_reason: str | None
    alias: Alias
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    latency_ms: int
    usage_reported: bool = True


@dataclass(frozen=True)
class TokenEvent:
    text: str
    type: Literal["token"] = "token"


@dataclass(frozen=True)
class ToolCallDeltaEvent:
    index: int
    id: str | None
    name: str | None
    arguments_delta: str
    type: Literal["tool_call_delta"] = "tool_call_delta"


@dataclass(frozen=True)
class DoneEvent:
    completion: Completion
    type: Literal["done"] = "done"


StreamEvent = TokenEvent | ToolCallDeltaEvent | DoneEvent
TransportEvent = TokenEvent | ToolCallDeltaEvent | RawCompletion


@dataclass
class ToolCallAccumulator:
    """Assembles streamed tool-call deltas (OpenAI streams them by index, in fragments)."""

    parts: dict[int, dict[str, str]] = field(default_factory=dict)

    def add(self, delta: ToolCallDeltaEvent) -> None:
        part = self.parts.setdefault(delta.index, {"id": "", "name": "", "arguments": ""})
        if delta.id:
            part["id"] = delta.id
        if delta.name:
            part["name"] += delta.name
        part["arguments"] += delta.arguments_delta

    def calls(self) -> list[ToolCall]:
        return [
            ToolCall(id=p["id"] or f"call_{i}", name=p["name"], arguments=p["arguments"])
            for i, p in sorted(self.parts.items())
        ]
