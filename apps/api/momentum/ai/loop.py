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
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.actions import ProposedCall, Source, apply_action, propose
from momentum.ai.llm import LLM
from momentum.ai.prefs import get_prefs
from momentum.ai.tools.registry import ToolRegistry
from momentum.ai.types import (
    Alias,
    Completion,
    DoneEvent,
    Msg,
    TokenEvent,
    ToolCall,
    ToolSchema,
)
from momentum.core.context import Ctx
from momentum.domain.workspace.service import get_ai_config

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
OUT_OF_STEPS = "I couldn't finish that in the steps I'm allowed. Try a narrower request."


@dataclass
class LoopResult:
    text: str
    proposals: list[ProposedCall] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    tools_used: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    # everything sent as ``token`` events when streaming (text of every step, in order)
    streamed: str = ""


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
    stream: bool = False,
) -> LoopResult:
    """Run until the model answers without tool calls (or ``max_steps`` model calls).

    With ``stream`` (chat), each step's text is sent as ``token`` events while it arrives, so
    the answer appears word by word; ``result.streamed`` is what the user saw."""
    result = LoopResult(text="")
    schemas = registry.schemas()
    seen: set[tuple[str, str]] = set()
    for step in range(max_steps):
        result.steps = step + 1
        if stream:
            c = await _streamed_step(
                llm,
                ctx,
                result,
                emit,
                alias,
                messages,
                schemas,
                feature,
                prompt_version,
                max_tokens,
            )
        else:
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
        result.tokens_in += c.tokens_in
        result.tokens_out += c.tokens_out
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
    if stream:
        await _stream_text(result, emit, OUT_OF_STEPS)
    return result


async def _stream_text(result: LoopResult, emit: Emit, text: str) -> None:
    if result.streamed and not result.streamed.endswith("\n"):
        result.streamed += "\n\n"
        await emit("token", {"text": "\n\n"})
    result.streamed += text
    await emit("token", {"text": text})


async def _streamed_step(
    llm: LLM,
    ctx: Ctx,
    result: LoopResult,
    emit: Emit,
    alias: Alias,
    messages: list[Msg],
    schemas: list[ToolSchema],
    feature: str,
    prompt_version: str | None,
    max_tokens: int,
) -> Completion:
    first = True
    async for ev in llm.stream(
        alias=alias,
        messages=messages,
        tools=schemas,
        feature=feature,
        ctx=ctx,
        prompt_version=prompt_version,
        max_tokens=max_tokens,
        temperature=0,
    ):
        if isinstance(ev, TokenEvent) and ev.text:
            if first:  # a new step's text starts a new paragraph
                first = False
                await _stream_text(result, emit, ev.text)
            else:
                result.streamed += ev.text
                await emit("token", {"text": ev.text})
        elif isinstance(ev, DoneEvent):
            return ev.completion
    raise RuntimeError("stream ended without a result")  # LLM.stream always ends with DoneEvent


async def emit_proposals(
    session: AsyncSession,
    ctx: Ctx,
    registry: ToolRegistry,
    result: LoopResult,
    emit: Emit,
    *,
    source: Source,
    source_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Turn the loop's previews into one ``ai_actions`` row (``action_proposed``), auto-applied
    only when it is low risk and the user turned that on (``action_applied``). Candidates from
    an ambiguous reference with nothing proposed become a ``clarify`` event. Returns the action
    id, if one was stored."""
    if not result.proposals:
        if result.candidates:
            await emit("clarify", {"question": result.text, "candidates": result.candidates[:8]})
        return None
    p = await propose(session, ctx, registry, result.proposals, source=source, source_id=source_id)
    if p.action is None:  # a preview passed in the loop but not on re-check (data changed)
        await emit(
            "error",
            {"reason": "stale", "message": "Things changed while I was working. Try again."},
        )
        return None
    action = p.action
    await emit(
        "action_proposed",
        {"action_id": str(action.id), "summary": action.summary, "risk": action.risk},
    )
    # An admin can switch auto-apply off workspace-wide (S3.5.2), on top of the user's own toggle.
    wants_auto_apply = (await get_prefs(session, ctx)).auto_apply_low_risk
    config = await get_ai_config(session, ctx.workspace_id)
    workspace_allows = config.allow_auto_apply is not False
    if action.risk == "low" and wants_auto_apply and workspace_allows:
        applied = await apply_action(session, ctx, registry, action.id)
        if applied.outcome == "applied":
            await emit(
                "action_applied",
                {"action_id": str(action.id), "batch_id": str(applied.action.applied_batch_id)},
            )
    return action.id
