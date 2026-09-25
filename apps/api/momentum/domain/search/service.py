"""S2.6.2: global search across tasks, projects, people, and comments.

Every predicate here filters **in SQL**, not in Python, per the roadmap's own AC. There is one
deliberate scope narrowing, disclosed here rather than silently made: task and comment visibility
is resolved purely through project membership (`visible_projects_clause`, reused unmodified from
`domain/access.py` — that module needs human approval to change, so this only ever calls its
existing functions). `get_visible_task`'s fuller per-task rules (a task visible only because you
personally follow/were-assigned it, even without project access) aren't reproduced here — every
other bulk endpoint this phase (fields' `field-values`, tags' `task-tags`, dependencies'
`blocked-tasks`, multi-homing's `other-placements`) already scopes the same way, for the same
reason: a single SQL-native project-membership join is what makes "permission-filtered in SQL"
actually possible without re-deriving `get_visible_task`'s ancestor-walk as a SQL predicate.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.domain.access import visible_projects_clause
from momentum.domain.comments.models import Comment
from momentum.domain.projects.models import Project
from momentum.domain.search.schemas import (
    ALL_TYPES,
    CommentHit,
    PersonHit,
    ProjectHit,
    SearchResultsOut,
    SearchType,
    TaskHit,
)
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.service import list_users


def _visible_project_ids(ctx: Ctx):  # type: ignore[no-untyped-def]
    return select(Project.id).where(visible_projects_clause(ctx))


def _task_visible_clause(ctx: Ctx):  # type: ignore[no-untyped-def]
    return Task.id.in_(
        select(TaskProject.task_id).where(TaskProject.project_id.in_(_visible_project_ids(ctx)))
    )


async def _search_tasks(
    session: AsyncSession,
    ctx: Ctx,
    q: str,
    *,
    project_id: str | None,
    assignee_id: str | None,
    completed: bool | None,
    limit: int,
) -> list[TaskHit]:
    tsquery = func.plainto_tsquery("simple", q)
    rank = func.ts_rank(Task.search_tsv, tsquery)
    query = select(Task, rank.label("rank")).where(
        Task.workspace_id == ctx.workspace_id,
        Task.deleted_at.is_(None),
        Task.parent_id.is_(None),
        _task_visible_clause(ctx),
        or_(Task.search_tsv.op("@@")(tsquery), Task.title.op("%")(q)),
    )
    if project_id:
        query = query.where(
            Task.id.in_(select(TaskProject.task_id).where(TaskProject.project_id == project_id))
        )
    if assignee_id:
        query = query.where(Task.assignee_id == assignee_id)
    if completed is not None:
        query = query.where(
            Task.completed_at.is_not(None) if completed else Task.completed_at.is_(None)
        )
    rows = (await session.execute(query.order_by(rank.desc(), Task.title).limit(limit))).all()
    tasks = [r[0] for r in rows]
    if not tasks:
        return []
    placements = (
        await session.execute(
            select(TaskProject.task_id, Project.id, Project.name)
            .join(Project, Project.id == TaskProject.project_id)
            .where(
                TaskProject.task_id.in_([t.id for t in tasks]),
                Project.id.in_(_visible_project_ids(ctx)),
            )
        )
    ).all()
    project_of: dict[str, tuple[str, str]] = {}
    for task_id, pid, pname in placements:
        project_of.setdefault(str(task_id), (str(pid), pname))
    return [
        TaskHit(
            id=t.id,
            title=t.title,
            type=t.type,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
            project_id=project_of.get(str(t.id), (None, None))[0],
            project_name=project_of.get(str(t.id), (None, None))[1],
        )
        for t in tasks
    ]


async def _search_projects(
    session: AsyncSession, ctx: Ctx, q: str, *, limit: int
) -> list[ProjectHit]:
    tsquery = func.plainto_tsquery("simple", q)
    rank = func.ts_rank(Project.search_tsv, tsquery)
    query = (
        select(Project)
        .where(
            visible_projects_clause(ctx),
            or_(Project.search_tsv.op("@@")(tsquery), Project.name.op("%")(q)),
        )
        .order_by(rank.desc(), Project.name)
        .limit(limit)
    )
    rows = (await session.execute(query)).scalars()
    return [ProjectHit(id=p.id, name=p.name, color=p.color) for p in rows]


async def _search_comments(
    session: AsyncSession, ctx: Ctx, q: str, *, project_id: str | None, limit: int
) -> list[CommentHit]:
    tsquery = func.plainto_tsquery("simple", q)
    rank = func.ts_rank(Comment.search_tsv, tsquery)
    query = (
        select(Comment, Task.title)
        .join(Task, Task.id == Comment.task_id)
        .where(
            Comment.workspace_id == ctx.workspace_id,
            Comment.deleted_at.is_(None),
            Task.deleted_at.is_(None),
            _task_visible_clause(ctx),
            Comment.search_tsv.op("@@")(tsquery),
        )
    )
    if project_id:
        query = query.where(
            Comment.task_id.in_(
                select(TaskProject.task_id).where(TaskProject.project_id == project_id)
            )
        )
    rows = (await session.execute(query.order_by(rank.desc()).limit(limit))).all()
    return [
        CommentHit(
            id=c.id,
            task_id=c.task_id,
            task_title=title,
            snippet=(c.body_text[:160] + "…") if len(c.body_text) > 160 else c.body_text,
        )
        for c, title in rows
    ]


async def search(
    session: AsyncSession,
    ctx: Ctx,
    q: str,
    *,
    types: tuple[SearchType, ...] = ALL_TYPES,
    project_id: str | None = None,
    assignee_id: str | None = None,
    completed: bool | None = None,
    limit: int = 8,
) -> SearchResultsOut:
    clean = q.strip()
    if not clean or ctx.actor.id is None:
        return SearchResultsOut(tasks=[], projects=[], people=[], comments=[])
    tasks = (
        await _search_tasks(
            session,
            ctx,
            clean,
            project_id=project_id,
            assignee_id=assignee_id,
            completed=completed,
            limit=limit,
        )
        if "task" in types
        else []
    )
    projects = (
        await _search_projects(session, ctx, clean, limit=limit) if "project" in types else []
    )
    people = (
        [
            PersonHit(id=u.id, name=u.name, email=u.email, avatar_url=u.avatar_url)
            for u in await list_users(session, ctx, q=clean, limit=limit)
        ]
        if "person" in types
        else []
    )
    comments = (
        await _search_comments(session, ctx, clean, project_id=project_id, limit=limit)
        if "comment" in types
        else []
    )
    return SearchResultsOut(tasks=tasks, projects=projects, people=people, comments=comments)
