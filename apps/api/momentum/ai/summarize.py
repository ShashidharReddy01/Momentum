"""S3.4.1 summaries: a task's comment thread, and an inbox catch-up.

Both use the ``fast`` alias and are **cached by content hash** in ``ai_summaries``: the hash
covers the prompt version, the model and exactly the content summarized, so a repeat request on
unchanged content costs nothing, and any new or edited comment (or notification) makes a new
summary. Thread summaries are also what ``task_ctx`` shows for long threads (S3.1.5).

Citations: a thread is given to the model as labelled comments ``[C1]…[Cn]`` (oldest first);
the answer cites those labels, which are mapped back to the comments here, and any ``[T-n]`` /
``[P:…]`` it mentions is resolved as the reader (``ai/citations.py``). A label that doesn't
exist in the thread is returned as invalid, never linked.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import citations, prompts
from momentum.ai.context.tokens import clip, safe
from momentum.ai.llm import LLM
from momentum.ai.models import AiSummary
from momentum.ai.prompts import Prompt
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.core.ids import new_id, task_key
from momentum.domain.access import get_visible_task
from momentum.domain.comments.models import Comment
from momentum.domain.notifications.models import Notification
from momentum.domain.tasks.models import Task
from momentum.domain.users.models import User

MAX_COMMENTS = 60  # the newest; older ones are counted, not sent
MAX_NOTIFICATIONS = 50
COMMENT_CHARS = 600
LABEL = re.compile(r"\[C(\d{1,3})\]")


@dataclass
class Summary:
    text: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    cached: bool = False
    count: int = 0  # comments / notifications summarized
    omitted: int = 0  # older comments not sent
    created_at: datetime | None = None


def _hash(prompt: Prompt, model: str, content: Any) -> str:
    raw = json.dumps([prompt.version, model, content], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _cached(
    session: AsyncSession, ctx: Ctx, entity_type: str, entity_id: uuid.UUID, kind: str, h: str
) -> AiSummary | None:
    return (
        await session.execute(
            select(AiSummary).where(
                AiSummary.workspace_id == ctx.workspace_id,
                AiSummary.entity_type == entity_type,
                AiSummary.entity_id == entity_id,
                AiSummary.kind == kind,
                AiSummary.content_hash == h,
            )
        )
    ).scalar_one_or_none()


async def _store(
    session: AsyncSession,
    ctx: Ctx,
    entity_type: str,
    entity_id: uuid.UUID,
    kind: str,
    h: str,
    text: str,
    model: str,
) -> AiSummary:
    # two people summarizing the same thread at once: the first insert wins, both get it
    await session.execute(
        insert(AiSummary)
        .values(
            id=new_id(),
            workspace_id=ctx.workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            kind=kind,
            content_hash=h,
            summary=text,
            model=model,
        )
        .on_conflict_do_nothing(index_elements=["entity_type", "entity_id", "kind", "content_hash"])
    )
    row = await _cached(session, ctx, entity_type, entity_id, kind, h)
    assert row is not None
    return row


async def _names(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    real = {i for i in ids if i is not None}
    if not real:
        return {}
    rows = await session.execute(select(User.id, User.name).where(User.id.in_(real)))
    return {i: n for i, n in rows.tuples()}


async def summarize_thread(
    session: AsyncSession, llm: LLM, ctx: Ctx, task_id: uuid.UUID, *, now: datetime
) -> Summary:
    """Summary of a visible task's comments (not deleted), newest ``MAX_COMMENTS``."""
    task, _, _ = await get_visible_task(session, ctx, task_id)
    comments = list(
        (
            await session.execute(
                select(Comment)
                .where(Comment.task_id == task.id, Comment.deleted_at.is_(None))
                .order_by(Comment.created_at, Comment.id)
            )
        ).scalars()
    )
    if not comments:
        raise ValidationFailed("There are no comments to summarize yet")
    omitted = max(0, len(comments) - MAX_COMMENTS)
    sent = comments[omitted:]
    names = await _names(session, {c.author_id for c in sent})
    prompt = prompts.load("summarize_thread")
    model = llm.model_for(prompt.alias)
    h = _hash(prompt, model, [[str(c.id), c.body_text, c.edited_at] for c in sent])
    labels = {n: c for n, c in enumerate(sent, start=1)}

    row = await _cached(session, ctx, "task", task.id, "thread", h)
    cached = row is not None
    if row is None:
        lines = [f'<thread task="{task_key(task.number)}" title="{safe(task.title)}">']
        if omitted:
            lines.append(f"({omitted} older comments not included)")
        for n, c in labels.items():
            who = safe(names.get(c.author_id, "unknown")) if c.author_id else "unknown"
            ai = " (AI)" if c.is_ai else ""
            when = c.created_at.date().isoformat()
            lines.append(f"[C{n}] {who}{ai} ({when}): {safe(clip(c.body_text, COMMENT_CHARS))}")
        lines.append("</thread>")
        out = await llm.complete(
            alias=prompt.alias,
            messages=[
                {"role": "system", "content": prompt.body},
                {
                    "role": "user",
                    "content": '<data source="comments">\n' + "\n".join(lines) + "\n</data>",
                },
            ],
            feature=prompt.feature,
            prompt_version=prompt.version,
            max_tokens=prompt.max_tokens,
            temperature=prompt.temperature,
            ctx=ctx,
        )
        row = await _store(session, ctx, "task", task.id, "thread", h, out.text.strip(), out.model)

    cites: list[dict[str, Any]] = []
    for n in dict.fromkeys(int(x) for x in LABEL.findall(row.summary)):
        comment = labels.get(n)
        cites.append(
            {
                "ref": f"[C{n}]",
                "type": "comment",
                "valid": comment is not None,
                "id": str(comment.id) if comment else None,
                "title": (names.get(comment.author_id) if comment and comment.author_id else None),
                "created_at": comment.created_at.isoformat() if comment else None,
            }
        )
    cites += [x.to_json() for x in await citations.resolve(session, ctx, row.summary)]
    return Summary(row.summary, cites, cached, len(sent), omitted, row.created_at)


async def summarize_inbox(session: AsyncSession, llm: LLM, ctx: Ctx, *, now: datetime) -> Summary:
    """Catch-up on my unread, unarchived notifications (newest ``MAX_NOTIFICATIONS``)."""
    if ctx.actor.id is None:
        raise ValidationFailed("Inbox catch-up is for people")
    notes = list(
        (
            await session.execute(
                select(Notification)
                .where(
                    Notification.user_id == ctx.actor.id,
                    Notification.read_at.is_(None),
                    Notification.archived_at.is_(None),
                )
                .order_by(Notification.created_at.desc(), Notification.id)
                .limit(MAX_NOTIFICATIONS)
            )
        ).scalars()
    )
    if not notes:
        raise ValidationFailed("You're all caught up: no unread notifications")
    task_ids = {n.entity_id for n in notes if n.entity_type == "task"}
    rows = await session.execute(select(Task.id, Task.number).where(Task.id.in_(task_ids)))
    numbers = {tid: number for tid, number in rows.tuples()}
    prompt = prompts.load("summarize_inbox")
    model = llm.model_for(prompt.alias)
    h = _hash(prompt, model, sorted(str(n.id) for n in notes))
    row = await _cached(session, ctx, "user", ctx.actor.id, "inbox", h)
    cached = row is not None
    if row is None:
        lines = []
        for i, n in enumerate(notes, start=1):
            key = f"[{task_key(numbers[n.entity_id])}] " if n.entity_id in numbers else ""
            snippet = f": {safe(clip(n.snippet, 160))}" if n.snippet else ""
            lines.append(
                f"N{i} ({n.kind.replace('_', ' ')}, {n.created_at.date().isoformat()}) "
                f"{key}{safe(n.title)}{snippet}"
            )
        out = await llm.complete(
            alias=prompt.alias,
            messages=[
                {"role": "system", "content": prompt.body},
                {
                    "role": "user",
                    "content": '<data source="inbox">\n' + "\n".join(lines) + "\n</data>",
                },
            ],
            feature=prompt.feature,
            prompt_version=prompt.version,
            max_tokens=prompt.max_tokens,
            temperature=prompt.temperature,
            ctx=ctx,
        )
        row = await _store(
            session, ctx, "user", ctx.actor.id, "inbox", h, out.text.strip(), out.model
        )
    cites = [x.to_json() for x in await citations.resolve(session, ctx, row.summary)]
    return Summary(row.summary, cites, cached, len(notes), 0, row.created_at)
