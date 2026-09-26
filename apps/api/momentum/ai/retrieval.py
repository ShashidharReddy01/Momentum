"""Hybrid retrieval (ai-architecture §6, S3.1.4).

``search(query)``: the query is embedded (``input_type="search_query"``); the top 40 chunks by
cosine distance and the top 40 keyword matches (the existing ``search_tsv`` columns, S2.6.2) are
fused by **reciprocal rank fusion** at the entity level (a task with three matching chunks
counts once, by its best chunk); optionally re-ranked (Cohere rerank via the gateway,
``MOMENTUM_AI_RERANK``, off by default); and the top ``k`` are returned with a snippet and
what a citation needs.

**Permissions are enforced in SQL, in both halves, before ranking** (``visibility.py``): private
content never reaches a non-member, not even as a candidate the model never sees.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Float, bindparam, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.embeddings import INDEXED, EntityType
from momentum.ai.llm import LLM
from momentum.ai.models import EMBED_DIM, Embedding
from momentum.ai.vector import Vector
from momentum.ai.visibility import visible_entity_clause, visible_project_ids
from momentum.core.context import Ctx
from momentum.core.ids import task_key
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject

CANDIDATES = 40
RRF_K = 60
SNIPPET_CHARS = 300
FEATURE = "retrieval"


@dataclass
class Hit:
    entity_type: EntityType
    entity_id: uuid.UUID
    score: float
    snippet: str
    title: str
    key: str | None = None  # T-123 for tasks, and for the task a comment/attachment is on
    task_id: uuid.UUID | None = None
    project: str | None = None
    sources: list[str] = field(default_factory=list)  # "vector" and/or "keyword"

    def citation(self) -> str:
        """How Mo cites it: ``[T-12]`` for tasks and their comments/files, ``[P:Name]`` for
        projects."""
        if self.key:
            return f"[{self.key}]"
        return f"[P:{self.title}]"

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": self.entity_type,
            "cite": self.citation(),
            "title": self.title,
            "snippet": self.snippet,
        }
        if self.project:
            out["project"] = self.project
        return out


async def _vector_candidates(
    session: AsyncSession, ctx: Ctx, qvec: list[float], model: str, types: tuple[str, ...]
) -> list[tuple[str, uuid.UUID, str]]:
    """Best chunk per entity, nearest first."""
    dist = Embedding.embedding.op("<=>", return_type=Float)(
        bindparam("q", qvec, type_=Vector(EMBED_DIM))
    )
    rows = (
        await session.execute(
            select(Embedding.entity_type, Embedding.entity_id, Embedding.text, dist.label("d"))
            .where(
                Embedding.workspace_id == ctx.workspace_id,
                Embedding.model == model,
                Embedding.entity_type.in_(types),
                visible_entity_clause(ctx, Embedding.entity_type, Embedding.entity_id),
            )
            .order_by(dist)
            .limit(CANDIDATES * 3)  # several chunks can belong to one entity
        )
    ).all()
    seen: dict[tuple[str, uuid.UUID], str] = {}
    for kind, eid, text, _ in rows:
        seen.setdefault((kind, eid), text)
    return [(k, e, t) for (k, e), t in list(seen.items())[:CANDIDATES]]


async def _keyword_candidates(
    session: AsyncSession, ctx: Ctx, query: str, types: tuple[str, ...]
) -> list[tuple[str, uuid.UUID]]:
    tsq = func.plainto_tsquery("simple", query)
    parts = []
    if "task" in types:
        parts.append(
            select(
                literal("task").label("t"),
                Task.id.label("id"),
                func.ts_rank(Task.search_tsv, tsq).label("r"),
            ).where(
                Task.workspace_id == ctx.workspace_id,
                or_(
                    Task.search_tsv.op("@@")(tsq),
                    func.lower(Task.title).contains(query.lower(), autoescape=True),
                ),
                visible_entity_clause(ctx, literal("task"), Task.id),
            )
        )
    if "comment" in types:
        parts.append(
            select(
                literal("comment").label("t"),
                Comment.id.label("id"),
                func.ts_rank(Comment.search_tsv, tsq).label("r"),
            ).where(
                Comment.workspace_id == ctx.workspace_id,
                Comment.search_tsv.op("@@")(tsq),
                visible_entity_clause(ctx, literal("comment"), Comment.id),
            )
        )
    if "project" in types:
        parts.append(
            select(
                literal("project").label("t"),
                Project.id.label("id"),
                func.ts_rank(Project.search_tsv, tsq).label("r"),
            ).where(
                Project.workspace_id == ctx.workspace_id,
                Project.search_tsv.op("@@")(tsq),
                visible_entity_clause(ctx, literal("project"), Project.id),
            )
        )
    if not parts:
        return []
    u = union_all(*parts).subquery()
    rows = (
        await session.execute(select(u.c.t, u.c.id).order_by(u.c.r.desc()).limit(CANDIDATES))
    ).all()
    return [(t, i) for t, i in rows]


def fuse(*rankings: list[tuple[str, uuid.UUID]]) -> list[tuple[tuple[str, uuid.UUID], float]]:
    """Reciprocal rank fusion: score = Σ 1 / (60 + rank) over the lists an item appears in."""
    scores: dict[tuple[str, uuid.UUID], float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], str(kv[0][1])))


async def _describe(
    session: AsyncSession, ctx: Ctx, items: list[tuple[str, uuid.UUID]]
) -> dict[tuple[str, uuid.UUID], dict[str, Any]]:
    """Title, key, task and project name for each hit (a few batched queries)."""
    by = {k: [i for t, i in items if t == k] for k in INDEXED}
    info: dict[tuple[str, uuid.UUID], dict[str, Any]] = {}
    task_of: dict[tuple[str, uuid.UUID], uuid.UUID] = {}
    for cid, tid, text in (
        await session.execute(
            select(Comment.id, Comment.task_id, Comment.body_text).where(
                Comment.id.in_(by["comment"])
            )
        )
    ).all():
        task_of[("comment", cid)] = tid
        info[("comment", cid)] = {"text": text}
    for aid, tid, name, text in (
        await session.execute(
            select(
                Attachment.id, Attachment.task_id, Attachment.filename, Attachment.text_extract
            ).where(Attachment.id.in_(by["attachment"]))
        )
    ).all():
        if tid is not None:
            task_of[("attachment", aid)] = tid
        info[("attachment", aid)] = {"title": name, "text": text or name}
    task_ids = set(by["task"]) | set(task_of.values())
    tasks = {
        t.id: t
        for t in (await session.execute(select(Task).where(Task.id.in_(task_ids)))).scalars()
    }
    # the top-level task's project, among projects the caller can see
    root: dict[uuid.UUID, uuid.UUID] = {}
    for t in tasks.values():
        cur = t
        for _ in range(8):
            if cur.parent_id is None:
                break
            parent = tasks.get(cur.parent_id) or await session.get(Task, cur.parent_id)
            if parent is None:
                break
            cur = parent
        root[t.id] = cur.id
    project_of: dict[uuid.UUID, str] = {}
    for tid, pname in (
        await session.execute(
            select(TaskProject.task_id, Project.name)
            .join(Project, Project.id == TaskProject.project_id)
            .where(
                TaskProject.task_id.in_(set(root.values())),
                Project.id.in_(visible_project_ids(ctx)),
            )
            .order_by(TaskProject.added_at)
        )
    ).all():
        project_of.setdefault(tid, pname)
    for pid, pname, brief in (
        await session.execute(
            select(Project.id, Project.name, Project.brief_text).where(
                Project.id.in_(by["project"])
            )
        )
    ).all():
        info[("project", pid)] = {"title": pname, "text": brief or pname}
    for key in items:
        kind, eid = key
        tid = eid if kind == "task" else task_of.get(key)
        task = tasks.get(tid) if tid else None
        d = info.setdefault(key, {})
        if task is not None:
            d["key"] = task_key(task.number)
            d["task_id"] = task.id
            d["project"] = project_of.get(root.get(task.id, task.id))
            if kind == "task":
                d["title"] = task.title
                d["text"] = "\n".join(p for p in (task.title, task.description_text) if p)
            elif kind == "comment":
                d["title"] = f"Comment on {task.title}"
    return info


def _snippet(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 1].rstrip() + "…"


async def search(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    query: str,
    *,
    k: int = 8,
    types: Iterable[EntityType] = INDEXED,
    rerank: bool | None = None,
    feature: str = FEATURE,
) -> list[Hit]:
    """The top ``k`` things the caller may see that match ``query`` (meaning or words)."""
    query = " ".join(query.split())
    if not query:
        return []
    kinds = tuple(types)
    model = llm.model_for("embed")
    (qvec,) = await llm.embed([query], input_type="search_query", feature=feature, ctx=ctx)
    vec = await _vector_candidates(session, ctx, qvec, model, kinds)
    kw = await _keyword_candidates(session, ctx, query, kinds)
    fused = fuse([(t, i) for t, i, _ in vec], kw)[:CANDIDATES]
    if not fused:
        return []
    chunk_text = {(t, i): text for t, i, text in vec}
    in_vec = {(t, i) for t, i, _ in vec}
    in_kw = set(kw)
    info = await _describe(session, ctx, [key for key, _ in fused])
    candidates: list[Hit] = []
    for key, score in fused:
        d = info.get(key, {})
        kind, eid = key
        if "title" not in d:  # vanished between ranking and describing (deleted meanwhile)
            continue
        candidates.append(
            Hit(
                entity_type=kind,  # type: ignore[arg-type]
                entity_id=eid,
                score=score,
                snippet=_snippet(chunk_text.get(key) or d.get("text") or d["title"]),
                title=d["title"],
                key=d.get("key"),
                task_id=d.get("task_id"),
                project=d.get("project"),
                sources=[
                    s for s, hit in (("vector", key in in_vec), ("keyword", key in in_kw)) if hit
                ],
            )
        )
    use_rerank = llm.settings.ai_rerank if rerank is None else rerank
    if use_rerank and len(candidates) > 1:
        order = await llm.rerank(
            query,
            [f"{h.title}\n{h.snippet}" for h in candidates],
            top_n=k,
            feature=f"{feature}:rerank",
            ctx=ctx,
        )
        return [Hit(**{**candidates[i].__dict__, "score": score}) for i, score in order[:k]]
    return candidates[:k]
