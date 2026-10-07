"""Phase 7.5 (spec §9.3): smart task creation. **Not a model call**: retrieval over the stored task
embeddings (the title is embedded with the ``embed`` alias when a gateway is configured; mock
embeddings are deterministic) plus trigram similarity and plain statistics.

- **Possible duplicates:** open tasks in the project the person can see with cosine ≥ 0.86 on the
  title embedding **or** trigram similarity ≥ 0.6, up to 3.
- **Suggestions**, from the 20 nearest tasks in the project (open or completed) plus the section's
  latest ones: the assignee if ≥ 40% of them had that person (active, assignable, not an agent);
  the due offset (median days from creation to due) if ≥ 5 of them have one; a custom field's
  most common value if ≥ 50%; tags on ≥ 50%. Each carries its reason in words.

Nothing is applied: the client shows chips the person clicks. Off when
``MOMENTUM_AI_TASK_SUGGESTIONS`` is false or the person hid them (``AiPrefs.task_suggestions``).
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Float, bindparam, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.models import EMBED_DIM, Embedding
from momentum.ai.prefs import get_prefs
from momentum.ai.vector import Vector
from momentum.ai.visibility import visible_task_ids
from momentum.core.context import Ctx
from momentum.core.ids import task_key
from momentum.domain.access import get_visible_project
from momentum.domain.fields.models import FieldDef, FieldValue
from momentum.domain.tags.models import Tag, TaskTag
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.service import today_for
from momentum.domain.users.models import User

MIN_WORDS = 3
DUP_COSINE = 0.86
DUP_TRIGRAM = 0.6
MAX_DUPLICATES = 3
NEIGHBOURS = 20
SECTION_RECENT = 10
ASSIGNEE_SHARE = 0.4
DUE_MIN = 5
FIELD_SHARE = 0.5
TAG_SHARE = 0.5


@dataclass
class Duplicate:
    id: uuid.UUID
    key: str
    title: str
    completed: bool
    assignee: str | None
    score: float


@dataclass
class Suggestion:
    kind: str  # assignee | due | field | tag
    label: str
    reason: str
    value: Any  # what applying sets: a user id, an ISO day, a field value, a tag id
    field_id: uuid.UUID | None = None
    days: int | None = None


@dataclass
class Suggestions:
    enabled: bool
    duplicates: list[Duplicate] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    neighbours: int = 0


async def enabled_for(session: AsyncSession, ctx: Ctx) -> bool:
    if not ctx.settings.ai_task_suggestions:
        return False
    return (await get_prefs(session, ctx)).task_suggestions


async def _similar(
    session: AsyncSession,
    llm: LLM | None,
    ctx: Ctx,
    pool: Any,
    title: str,
) -> dict[uuid.UUID, tuple[float, float]]:
    """task id → (cosine, trigram) for the project's visible tasks that resemble the title."""
    scores: dict[uuid.UUID, tuple[float, float]] = {}
    trigram = func.similarity(Task.title, title)
    for tid, tri in (
        await session.execute(
            select(Task.id, trigram).where(Task.id.in_(pool), trigram > 0).order_by(trigram.desc())
        )
    ).all():
        scores[tid] = (0.0, float(tri))
    if llm is not None and ctx.settings.ai_enabled:
        try:
            qvec = (await llm.embed([title], input_type="search_query", feature="embed", ctx=ctx))[
                0
            ]
        except AIUnavailable:
            qvec = None
        if qvec is not None:
            dist = Embedding.embedding.op("<=>", return_type=Float)(
                bindparam("q", qvec, type_=Vector(EMBED_DIM))
            )
            for tid, d in (
                await session.execute(
                    select(Embedding.entity_id, dist)
                    .where(
                        Embedding.workspace_id == ctx.workspace_id,
                        Embedding.entity_type == "task",
                        Embedding.chunk_no == 0,
                        Embedding.entity_id.in_(pool),
                    )
                    .order_by(dist)
                    .limit(NEIGHBOURS * 2)
                )
            ).all():
                cos = max(0.0, 1.0 - float(d))
                scores[tid] = (cos, scores.get(tid, (0.0, 0.0))[1])
    return scores


def _share(n: int, of: int) -> str:
    return f"{n} of {of} similar tasks"


async def suggest(
    session: AsyncSession,
    llm: LLM | None,
    ctx: Ctx,
    project_id: uuid.UUID,
    title: str,
    *,
    section_id: uuid.UUID | None = None,
) -> Suggestions:
    await get_visible_project(session, ctx, project_id)
    if not await enabled_for(session, ctx):
        return Suggestions(enabled=False)
    title = " ".join(title.split())
    if len(title.split()) < MIN_WORDS:
        return Suggestions(enabled=True)
    pool = (
        select(Task.id)
        .join(TaskProject, TaskProject.task_id == Task.id)
        .where(
            TaskProject.project_id == project_id,
            Task.deleted_at.is_(None),
            Task.parent_id.is_(None),
            Task.id.in_(visible_task_ids(ctx)),
        )
    )
    scores = await _similar(session, llm, ctx, pool, title)
    ranked = sorted(scores, key=lambda t: -max(scores[t]))
    near = ranked[:NEIGHBOURS]
    if section_id is not None:
        recent = (
            await session.execute(
                select(TaskProject.task_id)
                .where(
                    TaskProject.project_id == project_id,
                    TaskProject.section_id == section_id,
                    TaskProject.task_id.in_(pool),
                )
                .join(Task, Task.id == TaskProject.task_id)
                .order_by(Task.created_at.desc())
                .limit(SECTION_RECENT)
            )
        ).scalars()
        near += [t for t in recent if t not in near]
    tasks = {
        t.id: t for t in (await session.execute(select(Task).where(Task.id.in_(near)))).scalars()
    }
    near = [t for t in near if t in tasks]
    out = Suggestions(enabled=True, neighbours=len(near))
    users = {
        u.id: u
        for u in (
            await session.execute(
                select(User).where(
                    User.id.in_({t.assignee_id for t in tasks.values() if t.assignee_id})
                )
            )
        ).scalars()
    }

    # possible duplicates: open, very similar
    for tid in ranked:
        cos, tri = scores[tid]
        t = tasks.get(tid) or await session.get(Task, tid)
        if t is None or t.completed_at is not None:
            continue
        if cos >= DUP_COSINE or tri >= DUP_TRIGRAM:
            who = await session.get(User, t.assignee_id) if t.assignee_id else None
            out.duplicates.append(
                Duplicate(
                    t.id,
                    task_key(t.number),
                    t.title,
                    False,
                    who.name if who else None,
                    round(max(cos, tri), 3),
                )
            )
        if len(out.duplicates) >= MAX_DUPLICATES:
            break

    n = len(near)
    if not n:
        return out

    # assignee
    counts: Counter[uuid.UUID] = Counter(a for t in near if (a := tasks[t].assignee_id) is not None)
    if counts:
        uid, k = counts.most_common(1)[0]
        u = users.get(uid)
        if (
            u is not None
            and k / n >= ASSIGNEE_SHARE
            and u.status == "active"
            and not u.is_agent
            and u.workspace_id == ctx.workspace_id
        ):
            first = u.name.split()[0]
            out.suggestions.append(
                Suggestion(
                    "assignee", u.name, f"{_share(k, n)} were assigned to {first}", str(u.id)
                )
            )

    # due offset
    offsets = [
        (due_on - tasks[t].created_at.date()).days
        for t in near
        if (due_on := tasks[t].due_on) is not None
    ]
    if len(offsets) >= DUE_MIN:
        days = round(statistics.median(offsets))
        due = today_for(ctx) + timedelta(days=days)
        word = "day" if abs(days) == 1 else "days"
        out.suggestions.append(
            Suggestion(
                "due",
                f"Due in {days} {word}",
                f"{len(offsets)} similar tasks were due a median of {days} {word} after "
                "they were made",
                due.isoformat(),
                days=days,
            )
        )

    # custom fields: the most common value per field
    values: dict[uuid.UUID, Counter[str]] = {}
    raw: dict[tuple[uuid.UUID, str], Any] = {}
    for fid, value in (
        await session.execute(
            select(FieldValue.field_id, FieldValue.value).where(FieldValue.task_id.in_(near))
        )
    ).all():
        if value in (None, "", []):
            continue
        k_ = repr(value)
        values.setdefault(fid, Counter())[k_] += 1
        raw[(fid, k_)] = value
    if values:
        defs = {
            f.id: f
            for f in (
                await session.execute(
                    select(FieldDef).where(FieldDef.id.in_(values), FieldDef.deleted_at.is_(None))
                )
            ).scalars()
        }
        for fid, counter in values.items():
            f = defs.get(fid)
            if f is None:
                continue
            k_, c = counter.most_common(1)[0]
            if c / n < FIELD_SHARE:
                continue
            value = raw[(fid, k_)]
            shown = _label(f, value)
            out.suggestions.append(
                Suggestion(
                    "field",
                    f"{f.name}: {shown}",
                    f"{_share(c, n)} had {f.name} {shown}",
                    value,
                    field_id=fid,
                )
            )

    # tags on at least half
    tag_counts = Counter(
        (await session.execute(select(TaskTag.tag_id).where(TaskTag.task_id.in_(near)))).scalars()
    )
    if tag_counts:
        names = {
            t.id: t.name
            for t in (
                await session.execute(
                    select(Tag).where(Tag.id.in_(tag_counts), Tag.deleted_at.is_(None))
                )
            ).scalars()
        }
        for tag_id, c in tag_counts.most_common():
            if c / n < TAG_SHARE or tag_id not in names:
                continue
            out.suggestions.append(
                Suggestion(
                    "tag", names[tag_id], f"{_share(c, n)} were tagged {names[tag_id]}", str(tag_id)
                )
            )
    return out


def _label(f: FieldDef, value: Any) -> str:
    opts = {str(o.get("id")): str(o.get("label")) for o in f.options or [] if isinstance(o, dict)}
    if isinstance(value, list):
        return ", ".join(opts.get(str(v), str(v)) for v in value)
    if isinstance(value, bool):
        return "checked" if value else "not checked"
    return opts.get(str(value), str(value))
