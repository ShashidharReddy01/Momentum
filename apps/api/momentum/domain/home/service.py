"""Home: my next tasks, projects I worked in lately, and overdue work I'm waiting on
(phase-1.md S1.5.2). Read-only; everything respects the same visibility as the rest of the app."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Activity
from momentum.core.context import Ctx
from momentum.domain.access import task_ancestors, visible_projects_clause
from momentum.domain.comments.models import Comment
from momentum.domain.mytasks.models import BUCKETS, MyTaskPlacement
from momentum.domain.mytasks.service import list_my_tasks, without_hidden
from momentum.domain.projects.models import Favorite, Project
from momentum.domain.sections.models import Section
from momentum.domain.tasks.models import Follower, Task, TaskProject
from momentum.domain.tasks.service import today_for

PRIORITIES = 5
RECENT = 6
WAITING = 10
ACTIVITY_SCAN = 400  # my latest activity rows looked at for "recent projects"
RECENT_WINDOW = timedelta(days=60)
PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
BUCKET_RANK = {b: i for i, b in enumerate(BUCKETS)}


@dataclass
class RecentProject:
    project: Project
    team_name: str
    open_count: int
    overdue_count: int
    last_active_at: datetime | None


@dataclass
class Home:
    priorities: list[tuple[Task, MyTaskPlacement | None]]
    open: int
    due_today: int
    overdue: int
    recent: list[RecentProject]
    waiting: list[Task]
    waiting_total: int
    has_projects: bool


def priority_key(
    t: Task, placement: MyTaskPlacement | None
) -> tuple[bool, date, int, int, str, str]:
    """Earliest due first (overdue included), then priority, then where I put it in My Tasks."""
    return (
        t.due_on is None,
        t.due_on or date.max,
        PRIORITY_RANK.get(t.priority or "", 9),
        BUCKET_RANK.get(placement.bucket, 9) if placement else 9,
        placement.position if placement else "",
        str(t.id),
    )


async def _root_ids(session: AsyncSession, task_ids: set[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not task_ids:
        return {}
    tasks = (await session.execute(select(Task).where(Task.id.in_(task_ids)))).scalars()
    out = {}
    for t in tasks:
        if t.deleted_at is not None:
            continue
        chain = await task_ancestors(session, t) if t.parent_id else []
        if any(a.deleted_at is not None for a in chain):
            continue
        out[t.id] = chain[-1].id if chain else t.id
    return out


async def _recent_project_ids(session: AsyncSession, ctx: Ctx) -> list[tuple[uuid.UUID, datetime]]:
    """Projects touched by my own recent activity, most recent first."""
    since = datetime.now(UTC) - RECENT_WINDOW
    acts = (
        await session.execute(
            select(Activity.entity_type, Activity.entity_id, Activity.created_at)
            .where(
                Activity.workspace_id == ctx.workspace_id,
                Activity.actor_id == ctx.actor.id,
                Activity.entity_type.in_(("project", "section", "task", "comment")),
                Activity.created_at >= since,
            )
            .order_by(Activity.created_at.desc())
            .limit(ACTIVITY_SCAN)
        )
    ).all()
    ids = {
        kind: {a.entity_id for a in acts if a.entity_type == kind}
        for kind in ("section", "task", "comment")
    }
    section_project = (
        dict(
            (
                await session.execute(
                    select(Section.id, Section.project_id).where(Section.id.in_(ids["section"]))
                )
            )
            .tuples()
            .all()
        )
        if ids["section"]
        else {}
    )
    comment_task = (
        dict(
            (
                await session.execute(
                    select(Comment.id, Comment.task_id).where(Comment.id.in_(ids["comment"]))
                )
            )
            .tuples()
            .all()
        )
        if ids["comment"]
        else {}
    )
    roots = await _root_ids(session, ids["task"] | set(comment_task.values()))
    task_projects: dict[uuid.UUID, list[uuid.UUID]] = {}
    if roots:
        for root_id, project_id in (
            await session.execute(
                select(TaskProject.task_id, TaskProject.project_id).where(
                    TaskProject.task_id.in_(set(roots.values()))
                )
            )
        ).tuples():
            task_projects.setdefault(root_id, []).append(project_id)

    seen: dict[uuid.UUID, datetime] = {}
    for a in acts:
        pids: list[uuid.UUID] = []
        if a.entity_type == "project":
            pids = [a.entity_id]
        elif a.entity_type == "section" and a.entity_id in section_project:
            pids = [section_project[a.entity_id]]
        else:
            tid: uuid.UUID | None = (
                a.entity_id if a.entity_type == "task" else comment_task.get(a.entity_id)
            )
            if tid is not None and tid in roots:
                pids = task_projects.get(roots[tid], [])
        for pid in pids:
            seen.setdefault(pid, a.created_at)
    return list(seen.items())


async def _recent_projects(session: AsyncSession, ctx: Ctx, today: date) -> list[RecentProject]:
    from momentum.domain.teams.models import Team

    active = await _recent_project_ids(session, ctx)
    live = select(Project).where(
        visible_projects_clause(ctx), Project.archived_at.is_(None), Project.is_template.is_(False)
    )
    by_id: dict[uuid.UUID, Project] = {}
    if active:
        rows = await session.execute(live.where(Project.id.in_([pid for pid, _ in active])))
        by_id = {p.id: p for p in rows.scalars()}
    picked: list[tuple[Project, datetime | None]] = []
    for pid, at in active:
        if pid in by_id and len(picked) < RECENT:
            picked.append((by_id[pid], at))
    if len(picked) < RECENT:
        # not much history yet: starred projects first, then the most recently updated
        have = {p.id for p, _ in picked}
        starred = select(Favorite.entity_id).where(
            Favorite.user_id == ctx.actor.id, Favorite.entity_type == "project"
        )
        rest = live.where(Project.id.not_in(have)) if have else live
        more = await session.execute(
            rest.order_by(
                Project.id.in_(starred).desc(), Project.updated_at.desc(), Project.id
            ).limit(RECENT - len(picked))
        )
        picked += [(p, None) for p in more.scalars()]
    if not picked:
        return []
    pids = [p.id for p, _ in picked]
    teams = dict(
        (
            await session.execute(
                select(Team.id, Team.name).where(Team.id.in_({p.team_id for p, _ in picked}))
            )
        )
        .tuples()
        .all()
    )
    open_tasks = (
        select(
            TaskProject.project_id,
            func.count().label("open"),
            func.count().filter(Task.due_on < today).label("overdue"),
        )
        .join(Task, Task.id == TaskProject.task_id)
        .where(
            TaskProject.project_id.in_(pids),
            Task.deleted_at.is_(None),
            Task.completed_at.is_(None),
        )
        .group_by(TaskProject.project_id)
    )
    counts = {r.project_id: (r.open, r.overdue) for r in await session.execute(open_tasks)}
    return [
        RecentProject(
            project=p,
            team_name=teams.get(p.team_id, ""),
            open_count=counts.get(p.id, (0, 0))[0],
            overdue_count=counts.get(p.id, (0, 0))[1],
            last_active_at=at,
        )
        for p, at in picked
    ]


async def _waiting(session: AsyncSession, ctx: Ctx, today: date) -> tuple[list[Task], int]:
    """Overdue open tasks I created or follow that someone else is assigned to."""
    followed = select(Follower.task_id).where(Follower.user_id == ctx.actor.id)
    rows = await session.execute(
        select(Task)
        .where(
            Task.workspace_id == ctx.workspace_id,
            Task.deleted_at.is_(None),
            Task.completed_at.is_(None),
            Task.assignee_id.is_not(None),
            Task.assignee_id != ctx.actor.id,
            Task.due_on < today,
            or_(Task.created_by == ctx.actor.id, Task.id.in_(followed)),
        )
        .order_by(Task.due_on, Task.id)
    )
    tasks = await without_hidden(session, list(rows.scalars()))
    return tasks[:WAITING], len(tasks)


async def home(session: AsyncSession, ctx: Ctx) -> Home:
    assert ctx.actor.id is not None
    today = today_for(ctx)
    mine = await list_my_tasks(session, ctx)
    ranked = sorted(mine, key=lambda r: priority_key(*r))
    waiting, waiting_total = await _waiting(session, ctx, today)
    recent = await _recent_projects(session, ctx, today)
    has_projects = (
        bool(recent)
        or (
            await session.execute(select(Project.id).where(visible_projects_clause(ctx)).limit(1))
        ).first()
        is not None
    )
    return Home(
        priorities=ranked[:PRIORITIES],
        open=len(mine),
        due_today=sum(1 for t, _ in mine if t.due_on == today),
        overdue=sum(1 for t, _ in mine if t.due_on is not None and t.due_on < today),
        recent=recent,
        waiting=waiting,
        waiting_total=waiting_total,
        has_projects=has_projects,
    )
