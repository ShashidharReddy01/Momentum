"""Phase 7.5 (spec §9.1): "Catch me up" on Home, a project or a portfolio.

The facts are the visible activity since the person last looked (``user_visits``; at most 30 days
back, 7 days with no visit), by other people, grouped (completed, new, reassigned to me, due-date
changes, comments mentioning me, other comments, status updates, stage changes, files, blocked /
unblocked), counted, with the top items of each, capped at 150 events. The ``fast`` alias turns
them into a 5-8 line brief, "what needs you" first; a line is kept only if it cites a task key or
project from the facts and states only their numbers. With nothing new there is **no model call**:
the answer says "Nothing changed since <date>". Nothing is stored.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.grounding import data_block, grounded, match_cites, numbers_in
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.visibility import visible_project_ids, visible_task_ids
from momentum.core.activity import Activity
from momentum.core.context import Ctx
from momentum.core.ids import task_key
from momentum.domain.access import get_visible_project
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from momentum.domain.fields.models import FieldDef
from momentum.domain.notifications.models import Notification
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.users.models import User
from momentum.domain.visits import service as visits
from momentum.domain.visits.service import Scope
from momentum.reports.data import local_date

MAX_EVENTS = 150
CAP_DAYS = 30
DEFAULT_DAYS = 7
TOP = 8
HOME_CARD_MIN = 3  # the Home card shows when more than this many things changed
GROUPS = (
    "reassigned_to_me",
    "mentions",
    "due_changes",
    "blocked",
    "completed",
    "new",
    "unblocked",
    "comments",
    "status_updates",
    "stage_changes",
    "files",
)
NEEDS_YOU = ("reassigned_to_me", "mentions", "due_changes", "blocked")


class CatchUpLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=300)
    cites: list[str] = Field(default_factory=list, max_length=10)


class CatchUpDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[CatchUpLine] = Field(default_factory=list, max_length=10)


@dataclass
class Facts:
    scope: str
    since: datetime
    until: datetime
    total: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    groups: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    task_ids: dict[str, uuid.UUID] = field(default_factory=dict)  # key → id, for links

    def as_data(self, ctx: Ctx) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "since": str(local_date(self.since, ctx)),
            "changes": self.total,
            "counts": self.counts,
            "needs_you": {g: self.groups[g] for g in NEEDS_YOU if self.groups.get(g)},
            "everything_else": {
                g: self.groups[g] for g in GROUPS if g not in NEEDS_YOU and self.groups.get(g)
            },
        }


@dataclass
class CatchUp:
    facts: Facts
    lines: list[CatchUpLine]
    ai: bool

    @property
    def nothing_changed(self) -> bool:
        return self.facts.total == 0


async def resolve_since(
    session: AsyncSession,
    ctx: Ctx,
    scope: Scope,
    scope_id: uuid.UUID | None,
    since: datetime | None,
    now: datetime,
) -> datetime:
    """The asked time, else the last visit; never more than 30 days back (7 with no visit)."""
    floor = now - timedelta(days=CAP_DAYS)
    if since is None:
        seen = await visits.last_seen(session, ctx, scope, scope_id)
        since = seen if seen is not None else now - timedelta(days=DEFAULT_DAYS)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return max(since, floor)


async def _projects(
    session: AsyncSession, ctx: Ctx, scope: Scope, scope_id: uuid.UUID | None
) -> tuple[str, Any]:
    """(the scope in words, a select of the visible project ids in it)."""
    if scope == "project":
        assert scope_id is not None
        project, _ = await get_visible_project(session, ctx, scope_id)
        return f"the project {project.name}", select(Project.id).where(Project.id == project.id)
    if scope == "portfolio":
        assert scope_id is not None
        from momentum.domain.portfolios.membership import members_clause
        from momentum.domain.portfolios.service import get_portfolio

        p = await get_portfolio(session, ctx, scope_id)
        return f"the portfolio {p.name}", select(Project.id).where(
            members_clause(p), Project.id.in_(visible_project_ids(ctx))
        )
    return "everything you can see", visible_project_ids(ctx)


async def gather(
    session: AsyncSession,
    ctx: Ctx,
    scope: Scope,
    scope_id: uuid.UUID | None,
    since: datetime,
    now: datetime,
) -> Facts:
    """Visible activity by others since then, grouped and counted (at most 150 events)."""
    await visits.check_scope(session, ctx, scope, scope_id)
    label, project_ids = await _projects(session, ctx, scope, scope_id)
    me = ctx.actor.id
    tasks_in = (
        select(TaskProject.task_id)
        .where(TaskProject.project_id.in_(project_ids))
        .where(TaskProject.task_id.in_(visible_task_ids(ctx)))
    )
    files_in = select(Attachment.id).where(
        or_(Attachment.task_id.in_(tasks_in), Attachment.project_id.in_(project_ids))
    )
    comments_in = select(Comment.id).where(Comment.task_id.in_(tasks_in))
    rows = list(
        (
            await session.execute(
                select(Activity)
                .where(
                    Activity.workspace_id == ctx.workspace_id,
                    Activity.created_at >= since,
                    Activity.created_at <= now,
                    Activity.undone_at.is_(None),
                    or_(Activity.actor_id.is_(None), Activity.actor_id != me),
                    or_(
                        and_(Activity.entity_type == "task", Activity.entity_id.in_(tasks_in)),
                        and_(
                            Activity.entity_type == "project",
                            Activity.entity_id.in_(project_ids),
                        ),
                        and_(
                            Activity.entity_type == "attachment",
                            Activity.entity_id.in_(files_in),
                        ),
                        and_(
                            Activity.entity_type == "comment",
                            Activity.entity_id.in_(comments_in),
                        ),
                    ),
                )
                .order_by(Activity.created_at.desc())
                .limit(MAX_EVENTS * 3)
            )
        ).scalars()
    )
    mentions = list(
        (
            await session.execute(
                select(Notification).where(
                    Notification.user_id == me,
                    Notification.kind == "mentioned",
                    Notification.created_at >= since,
                    Notification.entity_type == "task",
                    Notification.entity_id.in_(tasks_in),
                )
            )
        ).scalars()
    )

    # names for what the rows point at
    task_ids = {r.entity_id for r in rows if r.entity_type == "task"}
    task_ids |= {n.entity_id for n in mentions}
    comment_task = {
        cid: tid
        for cid, tid in (
            await session.execute(
                select(Comment.id, Comment.task_id).where(
                    Comment.id.in_({r.entity_id for r in rows if r.entity_type == "comment"})
                )
            )
        ).all()
    }
    task_ids |= set(comment_task.values())
    tasks = {
        t.id: t
        for t in (await session.execute(select(Task).where(Task.id.in_(task_ids)))).scalars()
    }
    task_project = {
        tid: name
        for tid, name in (
            await session.execute(
                select(TaskProject.task_id, Project.name)
                .join(Project, Project.id == TaskProject.project_id)
                .where(TaskProject.task_id.in_(task_ids), TaskProject.project_id.in_(project_ids))
            )
        ).all()
    }
    projects = {
        pid: name
        for pid, name in (
            await session.execute(
                select(Project.id, Project.name).where(
                    Project.id.in_({r.entity_id for r in rows if r.entity_type == "project"})
                )
            )
        ).all()
    }
    files = {
        a.id: a
        for a in (
            await session.execute(
                select(Attachment).where(
                    Attachment.id.in_({r.entity_id for r in rows if r.entity_type == "attachment"})
                )
            )
        ).scalars()
    }
    people = {
        u.id: u.name
        for u in (
            await session.execute(
                select(User).where(User.id.in_({r.actor_id for r in rows if r.actor_id}))
            )
        ).scalars()
    }
    stage_names: dict[str, FieldDef] = {
        f.name: f
        for f in (
            await session.execute(
                select(FieldDef).where(
                    FieldDef.id.in_(
                        select(Portfolio.stage_field_id).where(
                            Portfolio.workspace_id == ctx.workspace_id,
                            Portfolio.stage_field_id.is_not(None),
                        )
                    )
                )
            )
        ).scalars()
    }

    out = Facts(scope=label, since=since, until=now)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_events = 0

    def task_item(tid: uuid.UUID, r: Activity | None, **extra: Any) -> dict[str, Any] | None:
        t = tasks.get(tid)
        if t is None or t.deleted_at is not None:
            return None
        key = task_key(t.number)
        out.task_ids[key] = t.id
        item: dict[str, Any] = {"key": key, "title": t.title}
        if task_project.get(tid):
            item["project"] = task_project[tid]
        if r is not None and r.actor_id:
            item["by"] = people.get(r.actor_id, "someone")
        if r is not None:
            item["on"] = str(local_date(r.created_at, ctx))
        return {**item, **extra}

    def add(group: str, item: dict[str, Any] | None) -> None:
        nonlocal seen_events
        if item is None or seen_events >= MAX_EVENTS:
            return
        seen_events += 1
        grouped[group].append(item)

    for n in mentions:
        add("mentions", task_item(n.entity_id, None, said=(n.snippet or "")[:160]))
    for r in rows:
        diff = r.diff or {}
        if r.entity_type == "task":
            if r.verb == "task.completed":
                add("completed", task_item(r.entity_id, r))
            elif r.verb == "task.created":
                add("new", task_item(r.entity_id, r))
            elif r.verb == "task.dependency_added":
                add("blocked", task_item(r.entity_id, r))
            elif r.verb == "task.unblocked":
                add("unblocked", task_item(r.entity_id, r))
            elif r.verb == "task.updated":
                assignee = diff.get("assignee_id")
                if (
                    isinstance(assignee, list)
                    and len(assignee) == 2
                    and str(assignee[1]) == str(me)
                ):
                    add("reassigned_to_me", task_item(r.entity_id, r))
                due = diff.get("due_on")
                if isinstance(due, list) and len(due) == 2:
                    add(
                        "due_changes",
                        task_item(r.entity_id, r, due_from=due[0], due_to=due[1]),
                    )
        elif r.entity_type == "comment" and r.verb == "comment.created":
            tid = comment_task.get(r.entity_id)
            if tid is not None and not any(n.entity_id == tid for n in mentions):
                add("comments", task_item(tid, r))
        elif r.entity_type == "project":
            name = projects.get(r.entity_id)
            if name is None:
                continue
            if r.verb == "project.status_updated":
                status = diff.get("status")
                title = diff.get("status_update")
                add(
                    "status_updates",
                    {
                        "project": name,
                        "status": status[1] if isinstance(status, list) else None,
                        "title": title[1] if isinstance(title, list) else None,
                        "by": people.get(r.actor_id, "someone") if r.actor_id else None,
                        "on": str(local_date(r.created_at, ctx)),
                    },
                )
            elif r.verb == "project.field_set":
                for k, v in diff.items():
                    fname = k.removeprefix("field:")
                    f = stage_names.get(fname)
                    if f is None or not isinstance(v, list) or len(v) != 2:
                        continue
                    labels = {str(o.get("id")): str(o.get("label")) for o in f.options or []}
                    add(
                        "stage_changes",
                        {
                            "project": name,
                            "from": labels.get(str(v[0])) if v[0] else None,
                            "to": labels.get(str(v[1]), str(v[1])),
                            "on": str(local_date(r.created_at, ctx)),
                        },
                    )
        elif r.entity_type == "attachment" and r.verb in ("attachment.created", "report.generated"):
            a = files.get(r.entity_id)
            if a is not None and a.deleted_at is None:
                where = task_project.get(a.task_id) if a.task_id else None
                add(
                    "files",
                    {
                        "file": a.filename,
                        "by": people.get(r.actor_id, "someone") if r.actor_id else None,
                        **({"project": where} if where else {}),
                    },
                )
    for g in GROUPS:
        if grouped.get(g):
            out.counts[g] = len(grouped[g])
            out.groups[g] = [
                {k: v for k, v in i.items() if v is not None} for i in grouped[g][:TOP]
            ]
    out.total = sum(out.counts.values())
    return out


def citables(facts: Facts) -> list[str]:
    out: list[str] = []
    for items in facts.groups.values():
        for i in items:
            out += [str(i[k]) for k in ("key", "project", "file") if i.get(k)]
    return list(dict.fromkeys(out))


def keep(draft: CatchUpDraft, facts: Facts, data: dict[str, Any]) -> list[CatchUpLine]:
    allowed = citables(facts)
    known = numbers_in(data)
    out: list[CatchUpLine] = []
    for line in draft.lines[:8]:
        text = " ".join(line.text.split())
        cites = match_cites(line.cites, allowed)
        if cites and grounded(text, known):
            out.append(CatchUpLine(text=text, cites=cites))
    return out


async def pending(
    session: AsyncSession,
    ctx: Ctx,
    scope: Scope,
    scope_id: uuid.UUID | None,
    *,
    now: datetime | None = None,
) -> Facts:
    """The counts only (no model call): what the Home card and the buttons show first."""
    now = now or datetime.now(UTC)
    since = await resolve_since(session, ctx, scope, scope_id, None, now)
    return await gather(session, ctx, scope, scope_id, since, now)


async def catch_up(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    scope: Scope,
    scope_id: uuid.UUID | None = None,
    *,
    since: datetime | None = None,
    now: datetime | None = None,
) -> CatchUp:
    now = now or datetime.now(UTC)
    start = await resolve_since(session, ctx, scope, scope_id, since, now)
    facts = await gather(session, ctx, scope, scope_id, start, now)
    if facts.total == 0:
        return CatchUp(facts, [], ai=False)  # nothing new: no model call
    data = facts.as_data(ctx)
    prompt = prompts.load("catch_up")
    draft = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=data_block("activity_since", data, citables(facts), scope=facts.scope),
        schema=CatchUpDraft,
        description="Submit the catch-up lines.",
    )
    return CatchUp(facts, keep(draft, facts, data), ai=True)
