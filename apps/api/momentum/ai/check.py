"""``momentum llm-check``: verify the configured gateway can do what Momentum needs.

Runs every probe through the real ``LLM`` gateway class (not a side channel), so a pass means
the production code path works. Nothing is written to the database: calls use a system context
and a no-op usage log.
"""

from __future__ import annotations

import functools
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import ValidationError

from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.tools.catalog import build_registry
from momentum.ai.tools.write_tools import UpdateTaskArgs
from momentum.ai.types import CHAT_ALIASES, DoneEvent, ToolCallAccumulator, ToolCallDeltaEvent
from momentum.core.context import Actor, Ctx

Status = Literal["pass", "fail", "warn"]
FEATURE = "llm_check"
STREAMING_TOOLS = "streaming with tool calls"

ADD_TOOL = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers and return the sum.",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
}
FORCE_ADD = {"type": "function", "function": {"name": "add"}}
TOOL_PROMPT = [{"role": "user", "content": "Use the add tool to add 2 and 3."}]
PING = [{"role": "user", "content": "Reply with the single word: pong"}]
STREAM_PROMPT = [{"role": "user", "content": "Count from one to five in words, one per line."}]
EMBED_TEXT = "Draft the pricing page copy for the website revamp"
CATALOG = "tool schemas (catalog)"
RERANK = "rerank"
RERANK_QUERY = "who is writing the pricing page text"
RERANK_DOCS = [
    "Book the venue for the team offsite",
    "Draft pricing page copy (Ana is writing it)",
    "Fix the login bug on mobile",
]
CATALOG_PROMPT = [
    {
        "role": "user",
        "content": "Use the update_task tool to set the due date of task T-12 to 2026-10-09.",
    }
]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    latency_ms: int
    detail: str


class _Fail(Exception):
    pass


def check_ctx(llm: LLM) -> Ctx:
    return Ctx(actor=Actor(id=None, workspace_id=uuid.UUID(int=0)), settings=llm.settings)


async def _timed(name: str, probe: Callable[[], Awaitable[tuple[Status, str]]]) -> CheckResult:
    started = time.monotonic()
    try:
        status, detail = await probe()
    except AIUnavailable as e:
        status, detail = "fail", f"{e.reason}: {e.internal_detail}"[:200]
    except _Fail as e:
        status, detail = "fail", str(e)
    except Exception as e:  # a probe must never crash the whole report
        status, detail = "fail", f"{type(e).__name__}: {e}"[:200]
    return CheckResult(name, status, int((time.monotonic() - started) * 1000), detail)


def _add_call_ok(name: str, arguments: str) -> tuple[Status, str]:
    if name != "add":
        raise _Fail(f"expected a call to 'add', got {name or 'no tool call'!r}")
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError as e:
        raise _Fail(f"tool arguments are not valid JSON: {arguments[:80]!r}") from e
    if args.get("a") != 2 or args.get("b") != 3:
        return "warn", f"called add with unexpected arguments {args}"
    return "pass", "add(a=2, b=3)"


async def run_llm_check(llm: LLM) -> list[CheckResult]:
    ctx = check_ctx(llm)
    dim = llm.settings.llm_embed_dim
    results: list[CheckResult] = []

    async def chat(alias: str) -> tuple[Status, str]:
        c = await llm.complete(
            alias=alias,  # type: ignore[arg-type]
            messages=PING,
            feature=FEATURE,
            ctx=ctx,
            max_tokens=10,
        )
        if not c.text.strip():
            raise _Fail("empty reply")
        usage = "" if c.usage_reported else " (gateway reported no token usage)"
        return ("pass" if c.usage_reported else "warn"), f"{c.model}: {c.text.strip()[:40]}{usage}"

    for alias in ("default", *[a for a in CHAT_ALIASES if a != "default"]):
        results.append(await _timed(f"basic chat ({alias})", functools.partial(chat, alias)))

    async def tools() -> tuple[Status, str]:
        c = await llm.complete(
            alias="default",
            messages=TOOL_PROMPT,
            tools=[ADD_TOOL],
            tool_choice=FORCE_ADD,
            feature=FEATURE,
            ctx=ctx,
            max_tokens=100,
        )
        if not c.tool_calls:
            raise _Fail("no tool call returned")
        return _add_call_ok(c.tool_calls[0].name, c.tool_calls[0].arguments)

    results.append(await _timed("tool calling", tools))

    async def catalog_tools() -> tuple[Status, str]:
        # Every real tool schema in one request: the gateway (and the provider behind it) must
        # accept their shapes (nullable fields, dates, nested references), and the model's
        # arguments must validate against the same Pydantic model the registry uses.
        schemas = build_registry().schemas()
        c = await llm.complete(
            alias="default",
            messages=CATALOG_PROMPT,
            tools=schemas,
            tool_choice={"type": "function", "function": {"name": "update_task"}},
            feature=FEATURE,
            ctx=ctx,
            max_tokens=300,
        )
        if not c.tool_calls or c.tool_calls[0].name != "update_task":
            raise _Fail("no update_task call returned")
        try:
            args = UpdateTaskArgs.model_validate(c.tool_calls[0].args())
        except (ValueError, ValidationError) as e:
            raise _Fail(f"arguments don't validate: {str(e)[:120]}") from e
        if (args.task.key or "").upper() != "T-12" or args.due_on != date(2026, 10, 9):
            return (
                "warn",
                f"{len(schemas)} schemas accepted; unexpected arguments "
                f"{c.tool_calls[0].arguments[:80]}",
            )
        return "pass", f"{len(schemas)} schemas accepted; update_task(T-12, due_on=2026-10-09)"

    results.append(await _timed(CATALOG, catalog_tools))

    async def streaming() -> tuple[Status, str]:
        tokens = 0
        done = None
        async for ev in llm.stream(
            alias="default", messages=STREAM_PROMPT, feature=FEATURE, ctx=ctx, max_tokens=60
        ):
            if isinstance(ev, DoneEvent):
                done = ev.completion
            elif ev.type == "token":
                tokens += 1
        if done is None or not done.text.strip():
            raise _Fail("stream produced no text")
        if tokens < 2:
            return "warn", "the whole reply arrived as one chunk (not really streamed)"
        if not done.usage_reported:
            return "warn", f"{tokens} chunks, but no token usage reported in the stream"
        return "pass", f"{tokens} chunks"

    results.append(await _timed("streaming", streaming))

    async def streaming_tools() -> tuple[Status, str]:
        acc = ToolCallAccumulator()
        async for ev in llm.stream(
            alias="default",
            messages=TOOL_PROMPT,
            tools=[ADD_TOOL],
            tool_choice=FORCE_ADD,
            feature=FEATURE,
            ctx=ctx,
            max_tokens=100,
            allow_tool_fallback=False,
        ):
            if isinstance(ev, ToolCallDeltaEvent):
                acc.add(ev)
        calls = acc.calls()
        if not calls:
            raise _Fail("no tool call deltas in the stream")
        return _add_call_ok(calls[0].name, calls[0].arguments)

    results.append(await _timed(STREAMING_TOOLS, streaming_tools))

    vectors: dict[str, list[float]] = {}

    async def embed(input_type: str) -> tuple[Status, str]:
        out = await llm.embed(
            [EMBED_TEXT],
            input_type=input_type,  # type: ignore[arg-type]
            feature=FEATURE,
            ctx=ctx,
        )
        if len(out) != 1:
            raise _Fail(f"expected 1 vector, got {len(out)}")
        if len(out[0]) != dim:
            raise _Fail(f"dimension {len(out[0])}, expected {dim} (MOMENTUM_LLM_EMBED_DIM)")
        vectors[input_type] = out[0]
        if input_type == "search_query" and vectors.get("search_document") == out[0]:
            return "warn", (
                f"dim {dim}, but identical to the search_document vector: the gateway may be "
                "dropping input_type"
            )
        return "pass", f"dim {dim}"

    for input_type in ("search_document", "search_query"):
        results.append(
            await _timed(f"embeddings ({input_type})", functools.partial(embed, input_type))
        )

    async def rerank() -> tuple[Status, str]:
        order = await llm.rerank(
            RERANK_QUERY, RERANK_DOCS, top_n=len(RERANK_DOCS), feature=FEATURE, ctx=ctx
        )
        if not order:
            raise _Fail("no ranking returned")
        if order[0][0] != 1:
            return "warn", f"ranked {RERANK_DOCS[order[0][0]]!r} first"
        return "pass", f"{llm.settings.llm_rerank_model}: relevant document ranked first"

    result = await _timed(RERANK, rerank)
    if result.status == "fail" and not llm.settings.ai_rerank:
        # rerank is optional and off: a gateway without it is fine, so this only warns
        result = CheckResult(
            result.name, "warn", result.latency_ms, f"(rerank is off) {result.detail}"
        )
    results.append(result)
    return results


def recommendations(results: list[CheckResult]) -> list[str]:
    recs: list[str] = []
    by_name = {r.name: r for r in results}
    stream_tools = by_name.get(STREAMING_TOOLS)
    if stream_tools and stream_tools.status == "fail":
        tools_ok = by_name.get("tool calling")
        if tools_ok and tools_ok.status != "fail":
            recs.append(
                "Streaming tool calls failed but non-streaming tool calls work: set "
                "MOMENTUM_LLM_SUPPORTS_STREAMING_TOOLS=false (tool steps then run non-streaming)."
            )
    if any(r.name.startswith("embeddings") and "dimension" in r.detail for r in results):
        recs.append(
            "Embedding dimension mismatch: fix MOMENTUM_LLM_EMBED_MODEL or MOMENTUM_LLM_EMBED_DIM "
            "(the embeddings table is vector(1024))."
        )
    return recs


def render(results: list[CheckResult], recs: list[str], *, header: str) -> str:
    width = max(len(r.name) for r in results)
    lines = [header, "", f"{'check'.ljust(width)}  result  latency  detail"]
    for r in results:
        lines.append(
            f"{r.name.ljust(width)}  {r.status.upper().ljust(6)}  "
            f"{(str(r.latency_ms) + ' ms').rjust(7)}  {r.detail}"
        )
    failed = sum(r.status == "fail" for r in results)
    warned = sum(r.status == "warn" for r in results)
    lines += ["", f"{len(results) - failed - warned} passed, {warned} warnings, {failed} failed"]
    lines += [f"Recommendation: {rec}" for rec in recs]
    return "\n".join(lines)
