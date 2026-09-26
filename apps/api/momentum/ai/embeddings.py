"""The embeddings pipeline (ai-architecture §6, S3.1.4).

What gets indexed: tasks (title + description), comments, attachments (file name + extracted
text) and project briefs (name + brief). Text is split into overlapping chunks of about 350
tokens (Cohere v3 reads ~512 per text), embedded with ``input_type="search_document"`` and
stored per chunk with a hash of model + text. Re-indexing an unchanged entity is free: when the
hashes match, nothing is sent to the gateway.

Keeping the index fresh is an **outbox consumer** (its own ``consumer_offsets`` row, like
realtime): ``index_changes`` reads events after its cursor, re-indexes each changed entity once,
and advances the cursor only past what it finished, so a gateway outage just delays indexing.
Deleted content has its rows removed. ``reindex`` rebuilds everything (or one type / since a
date) for the ``momentum reindex`` command.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.errors import AIDisabled, AIUnavailable, BudgetExceeded
from momentum.ai.llm import LLM
from momentum.ai.models import Embedding
from momentum.core.context import Actor, Ctx
from momentum.core.events import ConsumerOffset, OutboxEvent
from momentum.core.settings import Settings
from momentum.domain.access import task_ancestors
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task

EntityType = Literal["task", "comment", "attachment", "project"]
INDEXED: tuple[EntityType, ...] = ("task", "comment", "attachment", "project")
CONSUMER = "embeddings"
FEATURE = "embed"
CHUNK_CHARS = 1400  # ~350 tokens at ~4 chars/token
OVERLAP_CHARS = 200  # ~50 tokens
MAX_CHUNKS = 40  # a very long attachment is indexed up to ~14k tokens of text


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split on whitespace into chunks of at most ``size`` characters that overlap by about
    ``overlap`` characters, never cutting a word (a single longer word is cut)."""
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(words) and len(chunks) < MAX_CHUNKS:
        length, end = 0, start
        while end < len(words) and length + len(words[end]) + (1 if end > start else 0) <= size:
            length += len(words[end]) + (1 if end > start else 0)
            end += 1
        if end == start:  # one word longer than a chunk
            chunks.append(words[start][:size])
            start += 1
            continue
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        back, kept = end, 0
        while back > start + 1 and kept + len(words[back - 1]) + 1 <= overlap:
            back -= 1
            kept += len(words[back]) + 1
        start = back
    return chunks


def content_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


@dataclass(frozen=True)
class Source:
    workspace_id: uuid.UUID
    text: str


async def source_text(
    session: AsyncSession, entity_type: str, entity_id: uuid.UUID
) -> Source | None:
    """The text to index for an entity, or None when it is gone (deleted, or under a deleted
    task) and its embeddings should be removed."""
    if entity_type == "task":
        task = await session.get(Task, entity_id)
        if task is None or task.deleted_at is not None:
            return None
        if any(a.deleted_at is not None for a in await task_ancestors(session, task)):
            return None
        text = "\n".join(p for p in (task.title, task.description_text) if p)
        return Source(task.workspace_id, text)
    if entity_type == "comment":
        comment = await session.get(Comment, entity_id)
        if comment is None or comment.deleted_at is not None:
            return None
        task = await session.get(Task, comment.task_id)
        if task is None or task.deleted_at is not None:
            return None
        return Source(comment.workspace_id, f"Comment on {task.title}: {comment.body_text}")
    if entity_type == "attachment":
        att = await session.get(Attachment, entity_id)
        if att is None or att.deleted_at is not None:
            return None
        return Source(att.workspace_id, "\n".join(p for p in (att.filename, att.text_extract) if p))
    if entity_type == "project":
        project = await session.get(Project, entity_id)
        if project is None or project.deleted_at is not None or project.is_template:
            return None
        return Source(
            project.workspace_id, "\n".join(p for p in (project.name, project.brief_text) if p)
        )
    return None


def system_ctx(settings: Settings, workspace_id: uuid.UUID) -> Ctx:
    return Ctx(actor=Actor(id=None, workspace_id=workspace_id), settings=settings, via="system")


async def index_entity(
    session: AsyncSession, llm: LLM, entity_type: str, entity_id: uuid.UUID
) -> int:
    """Bring one entity's embeddings up to date. Returns how many chunks were (re-)embedded:
    0 when nothing changed or the entity is gone (its rows are then deleted)."""
    model = llm.model_for("embed")
    src = await source_text(session, entity_type, entity_id)
    current = list(
        (
            await session.execute(
                select(Embedding)
                .where(Embedding.entity_type == entity_type, Embedding.entity_id == entity_id)
                .order_by(Embedding.chunk_no)
            )
        ).scalars()
    )
    pieces = chunk(src.text) if src is not None else []
    hashes = [content_hash(model, p) for p in pieces]
    if [(e.model, e.content_hash) for e in current] == [(model, h) for h in hashes]:
        return 0
    if pieces and src is not None:
        vectors = await llm.embed(
            pieces,
            input_type="search_document",
            feature=FEATURE,
            ctx=system_ctx(llm.settings, src.workspace_id),
        )
    else:
        vectors = []
    await session.execute(
        delete(Embedding).where(
            Embedding.entity_type == entity_type, Embedding.entity_id == entity_id
        )
    )
    for i, (piece, h, vec) in enumerate(zip(pieces, hashes, vectors, strict=True)):
        assert src is not None
        session.add(
            Embedding(
                workspace_id=src.workspace_id,
                entity_type=entity_type,
                entity_id=entity_id,
                chunk_no=i,
                content_hash=h,
                text=piece,
                model=model,
                dim=len(vec),
                embedding=vec,
            )
        )
    await session.flush()
    return len(pieces)


async def _cursor(session: AsyncSession) -> ConsumerOffset:
    row = (
        await session.execute(
            select(ConsumerOffset).where(ConsumerOffset.consumer == CONSUMER).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = ConsumerOffset(consumer=CONSUMER, last_event_id=0)
        session.add(row)
        await session.flush()
    return row


@dataclass
class IndexRun:
    events: int = 0
    entities: int = 0
    chunks: int = 0
    stopped: str | None = None  # why the run stopped early (the AI failure kind)


async def index_changes(session: AsyncSession, llm: LLM, *, limit: int = 500) -> IndexRun:
    """Process outbox events after this consumer's cursor. The caller commits.

    The cursor row is locked for the run, so two workers never index the same events. On an
    AI failure the cursor stays before the entity that failed and the run stops: the next run
    retries it (nothing is skipped)."""
    run = IndexRun()
    cursor = await _cursor(session)
    events = list(
        (
            await session.execute(
                select(OutboxEvent.id, OutboxEvent.entity_type, OutboxEvent.entity_id)
                .where(OutboxEvent.id > cursor.last_event_id)
                .order_by(OutboxEvent.id)
                .limit(limit)
            )
        ).all()
    )
    done: set[tuple[str, uuid.UUID]] = set()
    for event_id, entity_type, entity_id in events:
        key = (entity_type, entity_id)
        if entity_type in INDEXED and key not in done:
            try:
                run.chunks += await index_entity(session, llm, entity_type, entity_id)
            except (AIUnavailable, AIDisabled, BudgetExceeded) as e:
                run.stopped = getattr(e, "reason", None) or type(e).__name__
                break
            done.add(key)
            run.entities += 1
        cursor.last_event_id = event_id
        run.events += 1
    await session.flush()
    return run


async def reindex(
    session: AsyncSession,
    llm: LLM,
    *,
    entity_types: Iterable[EntityType] = INDEXED,
    since: datetime | None = None,
) -> IndexRun:
    """Re-index every entity of the given types (optionally only those changed since a time).
    Unchanged content is skipped by hash, so this is cheap to re-run."""
    run = IndexRun()
    queries = {
        "task": (Task.id, Task.updated_at, Task.deleted_at),
        "comment": (Comment.id, Comment.created_at, Comment.deleted_at),
        "attachment": (Attachment.id, Attachment.created_at, Attachment.deleted_at),
        "project": (Project.id, Project.updated_at, Project.deleted_at),
    }
    for kind in entity_types:
        id_col, changed_col, deleted_col = queries[kind]
        stmt = select(id_col).where(deleted_col.is_(None))
        if since is not None:
            stmt = stmt.where(changed_col >= since)
        for (entity_id,) in (await session.execute(stmt)).all():
            run.chunks += await index_entity(session, llm, kind, entity_id)
            run.entities += 1
    return run
