"""Mock and record transports (`MOMENTUM_LLM_MODE=mock|record`).

**Mock** answers from YAML fixtures in the fixtures directory (default:
``ai/evals/fixtures/mock_responses``), one file per feature::

    responses:
      - match: {contains: "add 2 and 3"}      # substring of the last user message, or
        tool_calls: [{name: add, arguments: {a: 2, b: 3}}]
      - match: {key: 3f1c0a9b2e7d4c11}         # request_key() of a recorded request
        text: "..."
    default:                                   # the feature's generic fallback
      text: "..."

A feature with no file (or no match and no default) falls back to ``_default.yaml``. Every
fallback text says it is mock output, so it can't pass for real AI output in a demo.

**Record** calls the real gateway and appends each chat response to that feature's file under
its ``request_key`` so it replays in mock mode. Embeddings are not recorded: mock embeddings
are computed (see ``mock_embedding``), so fixtures would add nothing.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import yaml

from momentum.ai.transport import Transport
from momentum.ai.types import (
    ChatRequest,
    EmbedRequest,
    Msg,
    RawCompletion,
    RawEmbedding,
    TokenEvent,
    ToolCall,
    ToolCallDeltaEvent,
    TransportEvent,
)
from momentum.core.settings import Settings

PACKAGED_FIXTURES = Path(__file__).parent / "evals" / "fixtures" / "mock_responses"
FALLBACK_FEATURE = "_default"
FEATURE_FILE = re.compile(r"^[a-z0-9_:\-]+$")


def fixtures_dir(settings: Settings) -> Path:
    return Path(settings.llm_fixtures_dir) if settings.llm_fixtures_dir else PACKAGED_FIXTURES


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # multi-part content: keep the text parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return "" if content is None else json.dumps(content, sort_keys=True)


def request_key(messages: list[Msg], tools: list[dict[str, Any]] | None) -> str:
    """Stable 16-hex key for a request: non-system messages + tool names.

    System messages are excluded on purpose — they carry today's date and workspace memory, so
    including them would make every recorded fixture stale the next day.
    """
    convo = [
        [m.get("role"), _content_text(m.get("content")), m.get("tool_call_id")]
        for m in messages
        if m.get("role") != "system"
    ]
    names = sorted(t.get("function", {}).get("name", "") for t in tools or [])
    raw = json.dumps([convo, names], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _last_user_text(messages: list[Msg]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return _content_text(m.get("content"))
    return ""


def estimate_tokens(text: str) -> int:
    """Rough (~4 chars/token) count, used only for mock accounting."""
    return max(1, math.ceil(len(text) / 4)) if text else 0


def _feature_file(directory: Path, feature: str) -> Path | None:
    name = feature.replace(":", "__")
    if not FEATURE_FILE.match(feature):
        return None
    return directory / f"{name}.yaml"


def _load(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"mock fixture {path.name} must be a mapping")
    return data


def _entry_matches(entry: dict[str, Any], key: str, last_user: str) -> bool:
    match = entry.get("match") or {}
    if "key" in match:
        return bool(match["key"] == key)
    if "contains" in match:
        return str(match["contains"]).lower() in last_user.lower()
    return False


def _entry_to_completion(entry: dict[str, Any], req: ChatRequest) -> RawCompletion:
    calls = [
        ToolCall(
            id=f"call_mock_{i}",
            name=str(tc["name"]),
            arguments=json.dumps(tc.get("arguments") or {}, sort_keys=True),
        )
        for i, tc in enumerate(entry.get("tool_calls") or [])
    ]
    text = str(entry.get("text") or "")
    prompt = "".join(_content_text(m.get("content")) for m in req.messages)
    return RawCompletion(
        text=text,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
        tokens_in=estimate_tokens(prompt),
        tokens_out=estimate_tokens(text + "".join(c.arguments for c in calls)),
        model=f"mock/{req.alias}",
    )


_WORD = re.compile(r"[a-z0-9]+")


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _bucket(token: str, dim: int) -> tuple[int, float]:
    h = hashlib.sha256(token.encode()).digest()
    return int.from_bytes(h[:4], "big") % dim, 1.0 if h[4] & 1 else -1.0


def mock_embedding(text: str, input_type: str, dim: int) -> list[float]:
    """Deterministic, unit-length, *lexically meaningful* vector: hashed bag of stemmed words.

    Texts sharing words get a high cosine similarity, so retrieval code can be exercised in mock
    mode. A small input_type component makes query and document vectors differ slightly, like
    Cohere v3's do.
    """
    vec = [0.0] * dim
    for word in _WORD.findall(text.lower()):
        i, sign = _bucket(_stem(word), dim)
        vec[i] += sign
    i, sign = _bucket(f"__input_type__:{input_type}", dim)
    vec[i] += 0.05 * sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class MockTransport:
    def __init__(self, settings: Settings) -> None:
        self._dir = fixtures_dir(settings)
        self._dim = settings.llm_embed_dim

    def resolve(self, req: ChatRequest) -> RawCompletion:
        key = request_key(req.messages, req.tools)
        last_user = _last_user_text(req.messages)
        data = _load(_feature_file(self._dir, req.feature))
        for entry in data.get("responses") or []:
            if isinstance(entry, dict) and _entry_matches(entry, key, last_user):
                return _entry_to_completion(entry, req)
        default = data.get("default") or _load(self._dir / f"{FALLBACK_FEATURE}.yaml").get(
            "default"
        )
        if not isinstance(default, dict):
            default = {"text": f"(mock response: no fixture for feature '{req.feature}')"}
        return _entry_to_completion(default, req)

    async def complete(self, req: ChatRequest) -> RawCompletion:
        return self.resolve(req)

    async def stream(self, req: ChatRequest) -> AsyncIterator[TransportEvent]:
        raw = self.resolve(req)
        for piece in re.findall(r"\S+\s*|\s+", raw.text):
            yield TokenEvent(piece)
        for i, call in enumerate(raw.tool_calls):
            half = len(call.arguments) // 2
            yield ToolCallDeltaEvent(i, call.id, call.name, call.arguments[:half])
            yield ToolCallDeltaEvent(i, None, None, call.arguments[half:])
        yield raw

    async def embed(self, req: EmbedRequest) -> RawEmbedding:
        return RawEmbedding(
            vectors=[mock_embedding(t, req.input_type, self._dim) for t in req.texts],
            tokens_in=sum(estimate_tokens(t) for t in req.texts),
            model="mock/embed",
        )

    async def aclose(self) -> None:
        return None


class RecordingTransport:
    """Real gateway calls, with each chat response saved as a mock fixture."""

    def __init__(self, settings: Settings, inner: Transport) -> None:
        self._dir = fixtures_dir(settings)
        self._inner = inner

    def _save(self, req: ChatRequest, raw: RawCompletion) -> None:
        path = _feature_file(self._dir, req.feature)
        if path is None:
            return
        data = _load(path)
        key = request_key(req.messages, req.tools)
        entry: dict[str, Any] = {"match": {"key": key}, "text": raw.text}
        if raw.tool_calls:
            entry["tool_calls"] = [
                {"name": c.name, "arguments": _safe_args(c.arguments)} for c in raw.tool_calls
            ]
        responses = [
            e
            for e in data.get("responses") or []
            if not (isinstance(e, dict) and (e.get("match") or {}).get("key") == key)
        ]
        responses.append(entry)
        data["responses"] = responses
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    async def complete(self, req: ChatRequest) -> RawCompletion:
        raw = await self._inner.complete(req)
        self._save(req, raw)
        return raw

    async def stream(self, req: ChatRequest) -> AsyncIterator[TransportEvent]:
        async for ev in self._inner.stream(req):
            if isinstance(ev, RawCompletion):
                self._save(req, ev)
            yield ev

    async def embed(self, req: EmbedRequest) -> RawEmbedding:
        return await self._inner.embed(req)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _safe_args(raw: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_raw": raw}
