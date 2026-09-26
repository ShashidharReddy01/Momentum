"""The tool-calling loop shared by ⌘K commands (S3.2.2) and Ask Mo chat (S3.3.1).

Each step asks the model for the next move with the tool catalog attached. Read tools run and
their results go back to the model. **Write tools only preview** (dry run): their calls are
collected as proposals, turned into one ``ai_actions`` row by the caller, and applied only when
the user (or their auto-apply-low-risk setting) says so. A tool that fails (ambiguous reference,
not found, forbidden) is reported back to the model, which is told to ask rather than guess;
ambiguous candidates are also returned so the UI can offer them as choices.

Progress is reported through ``emit(type, data)`` so the caller can stream it (SSE).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.actions import ProposedCall
from momentum.ai.llm import LLM
from momentum.ai.tools.registry import ToolRegistry
from momentum.ai.types import Alias, Msg, ToolCall
from momentum.core.context import Ctx

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
OUT_OF_STEPS = "I couldn't finish that in the steps I'm allowed. Try a narrower request."


@dataclass
class LoopResult:
    text: str
    proposals: list[ProposedCall] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    tools_used: list[str] = field(default_factory=list)


def _assistant(text: str, calls: list[ToolCall]) -> Msg:
    return {
        "role": "assistant",
        "content": text or None,
        "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in calls
        ],
    }


async def run_tool_loop(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    registry: ToolRegistry,
    *,
    messages: list[Msg],
    feature: str,
    alias: Alias,
    emit: Emit,
    max_steps: int,
    prompt_version: str | None = None,
    max_tokens: int = 1000,
) -> LoopResult:
    """Run until the model answers without tool calls (or ``max_steps`` model calls)."""
    result = LoopResult(text="")
    schemas = registry.schemas()
    seen: set[tuple[str, str]] = set()
    for step in range(max_steps):
        result.steps = step + 1
        c = await llm.complete(
            alias=alias,
            messages=messages,
            tools=schemas,
            feature=feature,
            ctx=ctx,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
            temperature=0,
        )
        if not c.tool_calls:
            result.text = c.text.strip()
            return result
        messages.append(_assistant(c.text, c.tool_calls))
        for call in c.tool_calls:
            tool = registry.get(call.name)
            await emit("tool_call", {"id": call.id, "name": call.name})
            out = await registry.invoke(
                session, ctx, call.name, call.arguments, mode="dry_run", llm=llm
            )
            result.tools_used.append(call.name)
            writes = tool is not None and tool.spec.writes
            if out.ok and writes:
                key = (call.name, json.dumps(call.args(), sort_keys=True))
                if key not in seen:  # the model may re-preview the same change
                    seen.add(key)
                    result.proposals.append(ProposedCall(call.name, call.args()))
            error = out.result.error or {}
            if error.get("code") == "ambiguous":
                result.candidates += error.get("candidates") or []
            await emit(
                "tool_result",
                {
                    "id": call.id,
                    "name": call.name,
                    "ok": out.ok,
                    "summary": out.result.summary,
                    "preview": bool(out.ok and writes),
                },
            )
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": out.message_content()}
            )
    result.text = OUT_OF_STEPS
    return result
