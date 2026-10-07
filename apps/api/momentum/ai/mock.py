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

Multi-step tool loops (S3.2.2) add ``turn`` (1 = the first model call of the conversation, 2 =
after the first tool results, …) to ``match``, and may take argument values from the previous
tool result with a ``$last.<path>`` string: ``$last.data.tasks[].key`` is the list of every
task key in the last tool message's JSON (``[]`` maps over a list). Fixture ``text`` may embed
the same as ``{{$last.<path>}}`` (S3.3.1: an answer citing what the search found). This keeps
handwritten loop fixtures independent of ids and keys, which differ per database. ``turn``
counts from the latest user message, so earlier chat turns don't shift it.

A feature with no file (or no match and no default) falls back to ``_default.yaml``. Every
fallback text says it is mock output, so it can't pass for real AI output in a demo.

**Record** calls the real gateway and appends each chat response to that feature's file under
its ``request_key`` so it replays in mock mode. Embeddings are not recorded: mock embeddings
are computed (see ``mock_embedding``), so fixtures would add nothing.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import yaml

from momentum.ai.transport import Transport
from momentum.ai.types import (
    LAST_STEP_NOTE,
    ChatRequest,
    EmbedRequest,
    Msg,
    RawCompletion,
    RawEmbedding,
    RawRerank,
    RerankRequest,
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


def image_size(part: dict[str, Any]) -> tuple[int, int] | None:
    """Width and height of a data-URL image part (from the image header, never the pixels)."""
    url = str((part.get("image_url") or {}).get("url") or "")
    if not url.startswith("data:") or "," not in url:
        return None
    from PIL import Image

    try:
        with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as im:
            return int(im.size[0]), int(im.size[1])
    except (OSError, ValueError):
        return None


def _content_text(content: Any) -> str:
    """Text of a message. Image parts (Phase 7.5 vision) count by their size only, so a request
    key and a fixture match never depend on image bytes."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # multi-part content: keep the text parts
        out = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "image_url":
                size = image_size(p)
                out.append(f"[image {size[0]}x{size[1]}]" if size else "[image]")
            else:
                out.append(str(p.get("text", "")))
        return "".join(out)
    return "" if content is None else json.dumps(content, sort_keys=True)


def image_tokens(messages: list[Msg]) -> int:
    """Spec §4.7: each image counts (w*h)/750 input tokens."""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for p in content:
                if isinstance(p, dict) and p.get("type") == "image_url":
                    size = image_size(p)
                    if size:
                        total += (size[0] * size[1]) // 750
    return total


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


def _without_last_step(messages: list[Msg]) -> list[Msg]:
    """The tool loop's last-step note isn't part of the conversation a fixture describes."""
    suffix = f"\n\n{LAST_STEP_NOTE}"
    out: list[Msg] = []
    for m in messages:
        content = m.get("content")
        if content == LAST_STEP_NOTE:
            continue
        if isinstance(content, str) and content.endswith(suffix):
            m = {**m, "content": content[: -len(suffix)]}
        out.append(m)
    return out


def is_images_message(m: Msg) -> bool:
    """The user message the tool loop adds to carry look_at's images: part of the same turn,
    not a new question."""
    content = m.get("content")
    return (
        m.get("role") == "user"
        and isinstance(content, list)
        and any(
            isinstance(p, dict) and str(p.get("text", "")).startswith('<data source="look_at">')
            for p in content
        )
    )


def _last_user_text(messages: list[Msg]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user" and not is_images_message(m):
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


def _turn(messages: list[Msg]) -> int:
    """1 for the first model call after the latest user message; +1 per assistant message since
    (so a chat's earlier turns don't shift the numbering of a new question)."""
    turn = 1
    for m in reversed(messages):
        if m.get("role") == "user" and not is_images_message(m):
            break
        if m.get("role") == "assistant":
            turn += 1
    return turn


def _last_tool_result(messages: list[Msg]) -> Any:
    for m in reversed(messages):
        if m.get("role") == "tool":
            text = _content_text(m.get("content"))
            body = re.sub(r"^<data[^>]*>|</data>$", "", text.strip())
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return None
    return None


def _pick(value: Any, path: list[str]) -> Any:
    if not path:
        return value
    head, rest = path[0], path[1:]
    if head.endswith("[]"):
        items = value.get(head[:-2]) if isinstance(value, dict) else None
        return [_pick(i, rest) for i in items or []]
    return _pick(value.get(head) if isinstance(value, dict) else None, rest)


def _fill(args: Any, last: Any) -> Any:
    """Replace ``$last.<path>`` strings with values from the previous tool result."""
    if isinstance(args, str) and args.startswith("$last."):
        return _pick(last, args[len("$last.") :].split("."))
    if isinstance(args, dict):
        return {k: _fill(v, last) for k, v in args.items()}
    if isinstance(args, list):
        return [_fill(v, last) for v in args]
    return args


_TEXT_SLOT = re.compile(r"\{\{(\$last\.[^}]+|\$keys|\$data|\$cites)\}\}")
_CITES = re.compile(r"^Citable: (.*)$", re.M)
_DATA = re.compile(r"<data[^>]*>\n?(.*?)\n?</data>", re.S)
_KEY = re.compile(r"\bT-\d+\b")


def _fill_text(text: str, last: Any, user_text: str = "") -> str:
    """``{{$last.<path>}}`` in fixture text → that value (a list joined with spaces, a missing
    value as "(none)"), e.g. citations taken from the search the loop just ran. ``{{$keys}}`` →
    every task key in the last user message, as citations (``[T-1] [T-4]``), for features whose
    data is in the prompt rather than in a tool result (summaries, status drafts). ``{{$cites}}``
    → the first three entries of the message's ``Citable:`` line (report narratives). ``{{$data}}``
    → the content of the last user message's ``<data>`` block (writing help echoes it)."""

    def one(m: re.Match[str]) -> str:
        if m.group(1) == "$data":  # the (first) <data> block of the last user message
            found = _DATA.search(user_text)
            return found.group(1) if found else ""
        if m.group(1) == "$cites":  # report narratives: the first citable names and keys
            found = _CITES.search(user_text)
            items = [x.strip() for x in found.group(1).split("|")] if found else []
            return " | ".join(x for x in items[:3] if x) or "(none)"
        if m.group(1) == "$keys":
            keys = list(dict.fromkeys(_KEY.findall(user_text)))
            return " ".join(f"[{k}]" for k in keys) or "(none)"
        value = _fill(m.group(1), last)
        if isinstance(value, list):
            value = " ".join(str(v) for v in value if v is not None)
        return "(none)" if value in (None, "") else str(value)

    return _TEXT_SLOT.sub(one, text)


def _entry_matches(entry: dict[str, Any], key: str, last_user: str, turn: int = 1) -> bool:
    match = entry.get("match") or {}
    if "turn" in match and int(match["turn"]) != turn:
        return False
    if "key" in match:
        return bool(match["key"] == key)
    if "contains" in match:
        return str(match["contains"]).lower() in last_user.lower()
    return False


def _fill_strings(value: Any, last: Any, user: str) -> Any:
    """``{{…}}`` slots inside string arguments (structured-output fixtures)."""
    if isinstance(value, str) and "{{" in value:
        return _fill_text(value, last, user)
    if isinstance(value, dict):
        return {k: _fill_strings(v, last, user) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill_strings(v, last, user) for v in value]
    return value


def _entry_to_completion(entry: dict[str, Any], req: ChatRequest) -> RawCompletion:
    last = _last_tool_result(req.messages)
    user = _last_user_text(req.messages)
    calls = [
        ToolCall(
            id=f"call_mock_{_turn(req.messages)}_{i}",
            name=str(tc["name"]),
            arguments=json.dumps(
                _fill_strings(_fill(tc.get("arguments") or {}, last), last, user), sort_keys=True
            ),
        )
        for i, tc in enumerate(entry.get("tool_calls") or [])
    ]
    text = _fill_text(str(entry.get("text") or ""), last, user)
    prompt = "".join(_content_text(m.get("content")) for m in req.messages)
    return RawCompletion(
        text=text,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
        tokens_in=estimate_tokens(prompt) + image_tokens(req.messages),
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
        messages = _without_last_step(req.messages)
        key = request_key(messages, req.tools)
        last_user = _last_user_text(messages)
        data = _load(_feature_file(self._dir, req.feature))
        turn = _turn(messages)
        for entry in data.get("responses") or []:
            if isinstance(entry, dict) and _entry_matches(entry, key, last_user, turn):
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

    async def rerank(self, req: RerankRequest) -> RawRerank:
        """Deterministic stand-in: share of the query's (stemmed) words found in each document."""
        words = {_stem(w) for w in _WORD.findall(req.query.lower())}
        scored = []
        for i, doc in enumerate(req.documents):
            have = {_stem(w) for w in _WORD.findall(doc.lower())}
            scored.append((i, len(words & have) / max(len(words), 1)))
        scored.sort(key=lambda r: (-r[1], r[0]))
        return RawRerank(ranking=scored[: req.top_n], model="mock/rerank")

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
        key = request_key(_without_last_step(req.messages), req.tools)
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

    async def rerank(self, req: RerankRequest) -> RawRerank:
        return await self._inner.rerank(req)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _safe_args(raw: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_raw": raw}
