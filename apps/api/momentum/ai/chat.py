"""Ask Mo chat (S3.3.1): questions answered from the workspace, with citations.

A turn has two parts. ``start_turn`` stores the user's message (creating the conversation on the
first one) in the request's own transaction, so the question survives even if Mo then fails.
``run_chat`` answers it inside the SSE stream: hybrid retrieval for the question first (so an
empty result is known, and the prompt says to admit it), then the shared tool loop
(``ai/loop.py``) with streaming, so the answer arrives word by word. Afterwards every citation in
the answer is resolved **as the user** (``ai/citations.py``), write previews become one AI action
(same as ⌘K), and Mo's message is stored with its tool steps, citations and token totals.

Conversations are private to their owner. They are personal records, like AI preferences, not
shared work data, so they record no ``activity`` row (the same choice as ``ai_actions``);
changes Mo proposes are audited when applied.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import citations, prompts, retrieval
from momentum.ai.actions import get_action
from momentum.ai.context import (
    Screen,
    estimate_tokens,
    project_ctx,
    retrieval_ctx,
    screen_ctx,
    system_base,
    task_ctx,
    user_ctx,
)
from momentum.ai.context.tokens import clip, safe
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.loop import Emit, emit_proposals, run_tool_loop
from momentum.ai.memory import memory_for
from momentum.ai.models import AiConversation, AiMessage, Feedback
from momentum.ai.tools.registry import ToolRegistry
from momentum.ai.types import Msg
from momentum.core.context import Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.domain.access import get_visible_project, get_visible_task
from momentum.domain.workspace.models import Workspace

MAX_STEPS = 8  # ai-architecture §10
TIMEOUT_S = 60.0
HISTORY_MESSAGES = 12  # earlier messages sent with a new question (newest kept)
HISTORY_BUDGET = 3000  # tokens
TITLE_CHARS = 80
EMPTY_RETRIEVAL = (
    "Nothing in the workspace matched this question in search. If the tools don't find it "
    "either, tell the user you couldn't find it instead of answering from general knowledge."
)


@dataclass(frozen=True)
class Turn:
    conversation: AiConversation
    message: AiMessage


async def _conversation(
    session: AsyncSession, ctx: Ctx, conversation_id: uuid.UUID
) -> AiConversation:
    conv = await session.get(AiConversation, conversation_id)
    if conv is None or conv.user_id != ctx.actor.id or conv.workspace_id != ctx.workspace_id:
        raise NotFound("Conversation not found")
    return conv


async def _context_of(
    session: AsyncSession, ctx: Ctx, screen: Screen
) -> tuple[str, uuid.UUID | None]:
    """Where a new conversation starts: the task or project on screen, if the user can see it."""
    if screen.task_id is not None:
        try:
            await get_visible_task(session, ctx, screen.task_id)
            return "task", screen.task_id
        except NotFound:
            pass
    if screen.project_id is not None:
        try:
            await get_visible_project(session, ctx, screen.project_id)
            return "project", screen.project_id
        except NotFound:
            pass
    return "global", None


async def start_turn(
    session: AsyncSession,
    ctx: Ctx,
    text: str,
    *,
    conversation_id: uuid.UUID | None,
    screen: Screen,
) -> Turn:
    """Store the user's message (and a new conversation, on the first message)."""
    text = text.strip()
    if not text:
        raise ValidationFailed("Ask Mo something")
    if ctx.actor.id is None:
        raise ValidationFailed("Chat is for people")
    now = datetime.now(UTC)
    if conversation_id is None:
        kind, context_id = await _context_of(session, ctx, screen)
        conv = AiConversation(
            workspace_id=ctx.workspace_id,
            user_id=ctx.actor.id,
            context_type=kind,
            context_id=context_id,
            title=clip(" ".join(text.split()), TITLE_CHARS),
            updated_at=now,
        )
        session.add(conv)
        await session.flush()
    else:
        conv = await _conversation(session, ctx, conversation_id)
        conv.updated_at = now
    msg = AiMessage(
        workspace_id=ctx.workspace_id,
        conversation_id=conv.id,
        role="user",
        content={"text": text},
    )
    session.add(msg)
    await session.flush()
    return Turn(conv, msg)


async def _history(session: AsyncSession, conv_id: uuid.UUID) -> list[AiMessage]:
    return list(
        (
            await session.execute(
                select(AiMessage)
                .where(AiMessage.conversation_id == conv_id)
                .order_by(AiMessage.created_at, AiMessage.id)
            )
        ).scalars()
    )


def _as_messages(history: list[AiMessage]) -> list[Msg]:
    """Earlier turns as plain text (tool traffic isn't replayed), newest kept within budget.
    The user's words stay wrapped as data; Mo's own earlier answers are plain assistant text."""
    out: list[Msg] = []
    used = 0
    for m in reversed(history[-HISTORY_MESSAGES:]):
        text = str((m.content or {}).get("text") or "")
        if not text:
            continue
        cost = estimate_tokens(text)
        if used + cost > HISTORY_BUDGET and out:
            break
        used += cost
        if m.role == "user":
            out.append({"role": "user", "content": f'<data source="chat">{safe(text)}</data>'})
        else:
            out.append({"role": "assistant", "content": text})
    out.reverse()
    return out


async def _screen_block(
    session: AsyncSession, ctx: Ctx, screen: Screen, conv: AiConversation, now: datetime
) -> str:
    """The deep context for what the chat is about: the task on screen, else the project on
    screen, else the one the conversation started from."""
    task_id = screen.task_id or (conv.context_id if conv.context_type == "task" else None)
    project_id = screen.project_id or (conv.context_id if conv.context_type == "project" else None)
    try:
        if task_id is not None:
            return (await task_ctx(session, ctx, task_id, now=now)).text
        if project_id is not None:
            return (await project_ctx(session, ctx, project_id, now=now)).text
    except NotFound:
        pass
    return ""


async def run_chat(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    registry: ToolRegistry,
    turn_ids: tuple[uuid.UUID, uuid.UUID],
    *,
    screen: Screen,
    now: datetime,
    emit: Emit,
) -> None:
    conv_id, user_msg_id = turn_ids
    conv = await _conversation(session, ctx, conv_id)
    await emit(
        "conversation", {"conversation_id": str(conv.id), "user_message_id": str(user_msg_id)}
    )
    history = await _history(session, conv.id)
    question = next((str(m.content.get("text") or "") for m in history if m.id == user_msg_id), "")
    prompt = prompts.load("chat")
    ws = await session.get(Workspace, ctx.workspace_id)
    memory = await memory_for(session, ctx, project_id=screen.project_id)
    hits = await retrieval.search(session, llm, ctx, question, k=8)
    parts = [
        system_base(ctx, workspace_name=ws.name if ws else "", memory=memory, now=now).text,
        prompt.body,
        (await user_ctx(session, ctx, now=now)).text,
        (await screen_ctx(session, ctx, screen)).text,
        await _screen_block(session, ctx, screen, conv, now),
        "Search results for the latest message:\n" + retrieval_ctx(hits).text,
    ]
    if not hits:
        parts.append(EMPTY_RETRIEVAL)
    messages: list[Msg] = [
        {"role": "system", "content": "\n\n".join(p for p in parts if p)},
        *_as_messages(history),
    ]
    steps: dict[str, dict[str, Any]] = {}

    async def tracked(event: str, data: dict[str, Any]) -> None:
        if event == "tool_call":
            steps[str(data["id"])] = {"name": data["name"]}
        elif event == "tool_result":
            steps.setdefault(str(data["id"]), {"name": data["name"]}).update(
                ok=data["ok"], summary=data["summary"], preview=data["preview"]
            )
        await emit(event, data)

    try:
        async with asyncio.timeout(TIMEOUT_S):
            result = await run_tool_loop(
                session,
                llm,
                ctx,
                registry,
                messages=messages,
                feature="chat",
                alias=prompt.alias,
                emit=tracked,
                max_steps=MAX_STEPS,
                prompt_version=prompt.version,
                max_tokens=prompt.max_tokens,
                stream=True,
            )
    except TimeoutError as e:
        raise AIUnavailable(reason="timeout") from e
    answer = result.streamed.strip()
    cites = await citations.resolve(session, ctx, answer)
    for c in cites:
        await emit("citation", c.to_json())
    action_id = await emit_proposals(
        session, ctx, registry, result, emit, source="chat", source_id=conv.id
    )
    grounded = any(c.valid for c in cites)
    msg = AiMessage(
        workspace_id=ctx.workspace_id,
        conversation_id=conv.id,
        role="assistant",
        content={
            "text": answer,
            "steps": list(steps.values()),
            "citations": [c.to_json() for c in cites],
            "action_id": str(action_id) if action_id else None,
            "candidates": result.candidates[:8] if not result.proposals else [],
            "grounded": grounded,
            "retrieved": len(hits),
        },
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )
    session.add(msg)
    conv.updated_at = datetime.now(UTC)
    await session.flush()
    await emit(
        "done",
        {"steps": result.steps, "message_id": str(msg.id), "grounded": grounded},
    )


# ---------------- history and feedback ----------------


async def list_conversations(
    session: AsyncSession, ctx: Ctx, *, limit: int = 50
) -> list[AiConversation]:
    return list(
        (
            await session.execute(
                select(AiConversation)
                .where(
                    AiConversation.user_id == ctx.actor.id,
                    AiConversation.workspace_id == ctx.workspace_id,
                )
                .order_by(AiConversation.updated_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


@dataclass(frozen=True)
class ConversationView:
    conversation: AiConversation
    messages: list[AiMessage]
    ratings: dict[uuid.UUID, int]


async def get_conversation(
    session: AsyncSession, ctx: Ctx, conversation_id: uuid.UUID
) -> ConversationView:
    """A conversation with its messages. Citations are **re-resolved** for the reader now:
    access can change after an answer was written, and a link must never outlive it."""
    conv = await _conversation(session, ctx, conversation_id)
    messages = await _history(session, conv.id)
    for m in messages:
        if m.role == "assistant":
            fresh = await citations.resolve(session, ctx, str(m.content.get("text") or ""))
            session.expunge(m)  # display only: never written back
            m.content = {**m.content, "citations": [c.to_json() for c in fresh]}
    rows = await session.execute(
        select(Feedback.target_id, Feedback.rating).where(
            Feedback.user_id == ctx.actor.id,
            Feedback.target_type == "ai_message",
            Feedback.target_id.in_([m.id for m in messages]),
        )
    )
    ratings = {target: rating for target, rating in rows.tuples()}
    return ConversationView(conv, messages, ratings)


async def set_feedback(
    session: AsyncSession,
    ctx: Ctx,
    *,
    target_type: str,
    target_id: uuid.UUID,
    rating: int,
    comment: str | None,
) -> Feedback:
    """Rate one of Mo's answers (or an AI action) proposed for me; a new rating replaces mine."""
    if rating not in (-1, 1):
        raise ValidationFailed("Rating must be 1 or -1")
    if target_type == "ai_message":
        msg = await session.get(AiMessage, target_id)
        if msg is None or msg.role != "assistant":
            raise NotFound("Message not found")
        await _conversation(session, ctx, msg.conversation_id)
    elif target_type == "ai_action":
        # only the person it was proposed for can see (and rate) an action
        await get_action(session, ctx, target_id)
    else:
        raise ValidationFailed(f"Can't rate a {target_type}")
    fb = (
        await session.execute(
            select(Feedback).where(
                Feedback.user_id == ctx.actor.id,
                Feedback.target_type == target_type,
                Feedback.target_id == target_id,
            )
        )
    ).scalar_one_or_none()
    if fb is None:
        fb = Feedback(
            workspace_id=ctx.workspace_id,
            user_id=ctx.actor.id,
            target_type=target_type,
            target_id=target_id,
            rating=rating,
            comment=comment,
        )
        session.add(fb)
    else:
        fb.rating, fb.comment = rating, comment
    await session.flush()
    return fb
