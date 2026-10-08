"""Read tools (risk ``read``): look things up for the model. They run in any mode and change nothing
the user would notice (``list_my_tasks`` syncs My Tasks placements lazily, like the UI does).

Bulk listings scope task visibility through project membership (``visible_projects_clause``),
like every Phase 2 bulk endpoint and global search: a task visible to someone only personally
(assignee/follower without project access) is found by key or id (``get_visible_task``) but
not listed. Disclosed in the Phase 3 kickoff; widening it needs a per-task SQL clause in
``domain/access.py`` (human approval, CLAUDE.md §6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import aliased

from momentum.ai import chart, retrieval
from momentum.ai.embeddings import INDEXED
from momentum.ai.tools.base import ToolContext, ToolError, ToolResult, tool
from momentum.ai.tools.fields import fields_view, project_fields_view
from momentum.ai.tools.refs import (
    TaskRef,
    resolve_person,
    resolve_project,
    resolve_section,
    resolve_task,
)
from momentum.ai.tools.views import clip, iso, task_brief, task_briefs, user_names
from momentum.ai.visibility import visible_task_ids
from momentum.core.activity import Activity
from momentum.core.ids import task_key
from momentum.domain.access import visible_projects_clause
from momentum.domain.attachments.models import Attachment
from momentum.domain.comments.models import Comment
from momentum.domain.dashboards import query as dashboard_query
from momentum.domain.goals import service as goals
from momentum.domain.mytasks.service import list_my_tasks as svc_list_my_tasks
from momentum.domain.portfolios import service as portfolios
from momentum.domain.projects.models import Project
from momentum.domain.projects.service import project_members
from momentum.domain.sections.models import Section
from momentum.domain.sections.service import list_sections
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject
from momentum.domain.tasks.service import today_for
from momentum.domain.teams.models import Team
from momentum.domain.users.service import list_users
from momentum.domain.workload import rebalance
from momentum.domain.workload.rebalance import Move, Rebalance

Status = Literal["open", "completed", "any"]
READ = ("tasks:read",)


def _visible_task_clause(tc: ToolContext) -> ColumnElement[bool]:
    visible = select(Project.id).where(visible_projects_clause(tc.ctx))
    return Task.id.in_(select(TaskProject.task_id).where(TaskProject.project_id.in_(visible)))


def _status_clause(status: Status) -> ColumnElement[bool] | None:
    if status == "open":
        return Task.completed_at.is_(None)
    if status == "completed":
        return Task.completed_at.is_not(None)
    return None


def _ordered(stmt: Any, status: Status) -> Any:
    if status == "completed":
        return stmt.order_by(Task.completed_at.desc(), Task.number.desc())
    return stmt.order_by(Task.due_on.asc().nulls_last(), Task.number)


# ---------------- search_tasks ----------------


class SearchTasksArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(
        default=None, max_length=200, description="Words to look for in titles and descriptions"
    )
    project: str | None = Field(default=None, max_length=200, description="Project name or id")
    assignee: str | None = Field(
        default=None,
        max_length=200,
        description='"me", a name, an email, or "none" for unassigned tasks',
    )
    status: Status = Field(default="open", description="Open tasks by default")
    due_before: date | None = Field(default=None, description="Due on or before this date")
    due_after: date | None = Field(default=None, description="Due on or after this date")
    overdue: bool = Field(default=False, description="Only open tasks due before today")
    blocked: bool = Field(
        default=False, description="Only open tasks waiting on an unfinished blocking task"
    )
    limit: int = Field(default=20, ge=1, le=50)


@tool(
    name="search_tasks",
    description=(
        "Find tasks the user can see with structured filters (text, project, assignee, status, "
        "due range, overdue, blocked). Returns keys like T-123 to use with other tools."
    ),
    risk="read",
    scopes=READ,
)
async def search_tasks(tc: ToolContext, args: SearchTasksArgs) -> ToolResult:
    ctx = tc.ctx
    stmt = select(Task).where(
        Task.workspace_id == ctx.workspace_id,
        Task.deleted_at.is_(None),
        Task.parent_id.is_(None),
        _visible_task_clause(tc),
    )
    if args.text:
        q = " ".join(args.text.split())
        stmt = stmt.where(
            or_(
                Task.search_tsv.op("@@")(func.plainto_tsquery("simple", q)),
                func.lower(Task.title).contains(q.lower(), autoescape=True),
            )
        )
    if args.project:
        project, _ = await resolve_project(tc, args.project)
        stmt = stmt.where(
            Task.id.in_(select(TaskProject.task_id).where(TaskProject.project_id == project.id))
        )
    if args.assignee:
        if args.assignee.strip().lower() in ("none", "nobody", "unassigned"):
            stmt = stmt.where(Task.assignee_id.is_(None))
        else:
            person = await resolve_person(tc, args.assignee)
            stmt = stmt.where(Task.assignee_id == person.id)
    status: Status = "open" if args.overdue else args.status
    clause = _status_clause(status)
    if clause is not None:
        stmt = stmt.where(clause)
    if args.overdue:
        stmt = stmt.where(Task.due_on < today_for(ctx))
    if args.blocked:
        blocker = aliased(Task)
        waiting = (
            select(TaskDependency.task_id)
            .join(blocker, blocker.id == TaskDependency.depends_on_id)
            .where(blocker.deleted_at.is_(None), blocker.completed_at.is_(None))
        )
        stmt = stmt.where(Task.completed_at.is_(None), Task.id.in_(waiting))
    if args.due_before:
        stmt = stmt.where(Task.due_on <= args.due_before)
    if args.due_after:
        stmt = stmt.where(Task.due_on >= args.due_after)
    rows = list((await tc.session.execute(_ordered(stmt, status).limit(args.limit + 1))).scalars())
    more = len(rows) > args.limit
    tasks = await task_briefs(tc, rows[: args.limit])
    summary = f"{len(tasks)}{'+' if more else ''} task(s) found"
    return ToolResult.success(summary, {"tasks": tasks, "more": more})


# ---------------- get_task ----------------


class GetTaskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: TaskRef


@tool(
    name="get_task",
    description=(
        "Details of one task: fields, description, subtasks, blockers and recent comments."
    ),
    risk="read",
    scopes=READ,
)
async def get_task(tc: ToolContext, args: GetTaskArgs) -> ToolResult:
    s = tc.session
    task, _, role = await resolve_task(tc, args.task)
    detail = await task_brief(tc, task)
    detail["my_role"] = role
    files = await _task_attachments(tc, task)
    if files:  # S5.1.5: names only; get_attachment_text reads one
        detail["attachments"] = [a.filename for a in files]
    if task.description_text:
        detail["description"] = clip(task.description_text)
    custom = await fields_view(tc, task)
    if custom:  # S5.3.2: names, choices and values as labels (set with set_field_value)
        detail["custom_fields"] = custom
    subtasks = list(
        (
            await s.execute(
                select(Task)
                .where(Task.parent_id == task.id, Task.deleted_at.is_(None))
                .order_by(Task.parent_position, Task.id)
            )
        ).scalars()
    )
    if subtasks:
        detail["subtasks"] = [
            {"key": task_key(t.number), "title": t.title, "done": t.completed_at is not None}
            for t in subtasks
        ]
    blockers = list(
        (
            await s.execute(
                select(Task)
                .join(TaskDependency, TaskDependency.depends_on_id == Task.id)
                .where(
                    TaskDependency.task_id == task.id,
                    Task.deleted_at.is_(None),
                    Task.id.in_(visible_task_ids(tc.ctx)),  # never name a task the reader can't see
                )
                .order_by(Task.number)
            )
        ).scalars()
    )
    if blockers:
        detail["blocked_by"] = [
            {"key": task_key(t.number), "title": t.title, "done": t.completed_at is not None}
            for t in blockers
        ]
    comments = list(
        (
            await s.execute(
                select(Comment)
                .where(Comment.task_id == task.id, Comment.deleted_at.is_(None))
                .order_by(Comment.created_at.desc(), Comment.id.desc())
                .limit(5)
            )
        ).scalars()
    )
    if comments:
        names = await user_names(tc, {c.author_id for c in comments})
        detail["recent_comments"] = [
            {
                "author": names.get(c.author_id, "unknown") if c.author_id else "unknown",
                "at": iso(c.created_at),
                "text": clip(c.body_text, 300),
                **({"ai": True} if c.is_ai else {}),
            }
            for c in reversed(comments)
        ]
    return ToolResult.success(f"{detail['key']} {task.title}", {"task": detail})


# ---------------- get_project ----------------


class GetProjectArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(max_length=200, description="Project name or id")


@tool(
    name="get_project",
    description="Overview of a project: sections with task counts, overdue count and members.",
    risk="read",
    scopes=READ,
)
async def get_project(tc: ToolContext, args: GetProjectArgs) -> ToolResult:
    s = tc.session
    project, role = await resolve_project(tc, args.project)
    team = await s.get(Team, project.team_id)
    sections = await list_sections(s, project.id)
    counts = {
        (sid, done): n
        for sid, done, n in (
            await s.execute(
                select(
                    TaskProject.section_id,
                    Task.completed_at.is_not(None),
                    func.count(),
                )
                .join(Task, Task.id == TaskProject.task_id)
                .where(
                    TaskProject.project_id == project.id,
                    Task.deleted_at.is_(None),
                    Task.parent_id.is_(None),
                )
                .group_by(TaskProject.section_id, Task.completed_at.is_not(None))
            )
        ).all()
    }
    overdue = (
        await s.execute(
            select(func.count())
            .select_from(TaskProject)
            .join(Task, Task.id == TaskProject.task_id)
            .where(
                TaskProject.project_id == project.id,
                Task.deleted_at.is_(None),
                Task.completed_at.is_(None),
                Task.due_on < today_for(tc.ctx),
            )
        )
    ).scalar_one()
    members = await project_members(s, project.id)
    data: dict[str, Any] = {
        "id": str(project.id),
        "name": project.name,
        "team": team.name if team else None,
        "privacy": project.privacy,
        "my_role": role,
        "archived": project.archived_at is not None,
        "sections": [
            {
                "name": sec.name,
                "open": counts.get((sec.id, False), 0),
                "completed": counts.get((sec.id, True), 0),
            }
            for sec in sections
        ],
        "overdue": overdue,
        "members": [{"name": u.name, "role": r} for u, r in members],
    }
    if project.privacy == "team":
        data["note"] = "Members of the team can also edit this project"
    if project.start_on is not None:
        data["start_on"] = iso(project.start_on)
    if project.due_on is not None:
        data["due_on"] = iso(project.due_on)
    if project.brief_text:
        data["brief"] = project.brief_text[:1500]  # S6.2.1: the overview's brief, as plain text
    details = await project_fields_view(tc, project.id)
    if details:
        data["fields"] = details  # Phase 7.5: project fields (Stage, Contract value…), as labels
    return ToolResult.success(project.name, {"project": data})


# ---------------- get_section_tasks ----------------


class GetSectionTasksArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(max_length=200, description="Project name or id")
    section: str = Field(max_length=200, description="Section name or id")
    status: Status = "open"
    limit: int = Field(default=50, ge=1, le=100)


@tool(
    name="get_section_tasks",
    description="Tasks in one section of a project, in their board/list order.",
    risk="read",
    scopes=READ,
)
async def get_section_tasks(tc: ToolContext, args: GetSectionTasksArgs) -> ToolResult:
    project, _ = await resolve_project(tc, args.project)
    section = await resolve_section(tc, project.id, args.section)
    stmt = (
        select(Task)
        .join(TaskProject, TaskProject.task_id == Task.id)
        .where(
            TaskProject.project_id == project.id,
            TaskProject.section_id == section.id,
            Task.deleted_at.is_(None),
            Task.parent_id.is_(None),
        )
    )
    clause = _status_clause(args.status)
    if clause is not None:
        stmt = stmt.where(clause)
    rows = list(
        (
            await tc.session.execute(
                stmt.order_by(TaskProject.position, Task.id).limit(args.limit + 1)
            )
        ).scalars()
    )
    tasks = await task_briefs(tc, rows[: args.limit])
    return ToolResult.success(
        f"{len(tasks)} task(s) in {project.name} / {section.name}",
        {"tasks": tasks, "more": len(rows) > args.limit},
    )


# ---------------- list_my_tasks / list_user_tasks ----------------


class ListMyTasksArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "completed"] = "open"
    limit: int = Field(default=50, ge=1, le=100)


@tool(
    name="list_my_tasks",
    description=(
        "The user's own tasks from My Tasks, in bucket order (recently assigned, today, "
        "this week, later), or their recently completed tasks."
    ),
    risk="read",
    scopes=READ,
)
async def list_my_tasks(tc: ToolContext, args: ListMyTasksArgs) -> ToolResult:
    if tc.ctx.actor.id is None:
        raise ToolError("not_found", "There is no current user")
    rows = await svc_list_my_tasks(tc.session, tc.ctx, completed=args.status == "completed")
    rows = rows[: args.limit]
    briefs = await task_briefs(tc, [t for t, _ in rows])
    for b, (_, placement) in zip(briefs, rows, strict=True):
        if placement is not None and args.status == "open":
            b["bucket"] = placement.bucket
    return ToolResult.success(f"{len(briefs)} task(s)", {"tasks": briefs})


class ListUserTasksArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person: str = Field(max_length=200, description='A name, email, or "me"')
    status: Status = "open"
    limit: int = Field(default=30, ge=1, le=100)


@tool(
    name="list_user_tasks",
    description="Tasks assigned to a person, limited to projects the user can see.",
    risk="read",
    scopes=READ,
)
async def list_user_tasks(tc: ToolContext, args: ListUserTasksArgs) -> ToolResult:
    person = await resolve_person(tc, args.person)
    stmt = select(Task).where(
        Task.workspace_id == tc.ctx.workspace_id,
        Task.deleted_at.is_(None),
        Task.parent_id.is_(None),
        Task.assignee_id == person.id,
        _visible_task_clause(tc),
    )
    clause = _status_clause(args.status)
    if clause is not None:
        stmt = stmt.where(clause)
    rows = list(
        (await tc.session.execute(_ordered(stmt, args.status).limit(args.limit + 1))).scalars()
    )
    tasks = await task_briefs(tc, rows[: args.limit])
    return ToolResult.success(
        f"{len(tasks)} task(s) assigned to {person.name}",
        {"person": person.name, "tasks": tasks, "more": len(rows) > args.limit},
    )


# ---------------- get_project_activity ----------------


class GetProjectActivityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(max_length=200, description="Project name or id")
    since: date = Field(description="First day to include (the user's timezone)")
    until: date | None = Field(default=None, description="Last day to include; default today")
    limit: int = Field(default=100, ge=1, le=200)


VERB_TEXT = {
    "task.created": "created",
    "task.updated": "updated",
    "task.completed": "completed",
    "task.uncompleted": "reopened",
    "task.deleted": "deleted",
    "task.moved": "moved",
    "comment.created": "commented on",
}


@tool(
    name="get_project_activity",
    description=(
        "What changed in a project over a date range (created, completed, moved, edited tasks "
        "and comments), oldest first. Use it for status reports."
    ),
    risk="read",
    scopes=READ,
)
async def get_project_activity(tc: ToolContext, args: GetProjectActivityArgs) -> ToolResult:
    s, ctx = tc.session, tc.ctx
    project, _ = await resolve_project(tc, args.project)
    tz = ZoneInfo(ctx.actor.timezone)
    until = args.until or today_for(ctx)
    if until < args.since:
        raise ToolError("invalid_arguments", "until must be on or after since")
    start = datetime.combine(args.since, time.min, tz).astimezone(UTC)
    end = datetime.combine(until + timedelta(days=1), time.min, tz).astimezone(UTC)
    placed = select(TaskProject.task_id).where(TaskProject.project_id == project.id)
    in_project = or_(Task.id.in_(placed), Task.parent_id.in_(placed))
    task_ids = select(Task.id).where(in_project)
    comment_ids = select(Comment.id).where(Comment.task_id.in_(task_ids))
    section_ids = select(Section.id).where(Section.project_id == project.id)
    rows = list(
        (
            await s.execute(
                select(Activity)
                .where(
                    Activity.workspace_id == ctx.workspace_id,
                    Activity.created_at >= start,
                    Activity.created_at < end,
                    Activity.undone_at.is_(None),
                    or_(
                        and_(Activity.entity_type == "task", Activity.entity_id.in_(task_ids)),
                        and_(
                            Activity.entity_type == "comment",
                            Activity.entity_id.in_(comment_ids),
                        ),
                        and_(Activity.entity_type == "project", Activity.entity_id == project.id),
                        and_(
                            Activity.entity_type == "section", Activity.entity_id.in_(section_ids)
                        ),
                    ),
                )
                .order_by(Activity.created_at, Activity.id)
                .limit(args.limit + 1)
            )
        ).scalars()
    )
    # reorders alone are noise in a report (the task feed hides them too)
    rows = [r for r in rows if not (r.verb == "task.moved" and set(r.diff) == {"position"})]
    more = len(rows) > args.limit
    rows = rows[: args.limit]
    tasks = {
        t.id: t
        for t in (
            await s.execute(
                select(Task).where(
                    Task.id.in_([r.entity_id for r in rows if r.entity_type == "task"])
                )
            )
        ).scalars()
    }
    comment_task: dict[uuid.UUID, uuid.UUID] = {
        cid: tid
        for cid, tid in (
            await s.execute(
                select(Comment.id, Comment.task_id).where(
                    Comment.id.in_([r.entity_id for r in rows if r.entity_type == "comment"])
                )
            )
        ).all()
    }
    missing = set(comment_task.values()) - set(tasks)
    if missing:
        for extra in (await s.execute(select(Task).where(Task.id.in_(missing)))).scalars():
            tasks[extra.id] = extra
    names = await user_names(tc, {r.actor_id for r in rows})
    entries: list[dict[str, Any]] = []
    for r in rows:
        subject_id = comment_task.get(r.entity_id) if r.entity_type == "comment" else r.entity_id
        t = tasks.get(subject_id) if subject_id else None
        entry: dict[str, Any] = {
            "at": iso(r.created_at),
            "who": names.get(r.actor_id, "system") if r.actor_id else "system",
            "what": VERB_TEXT.get(r.verb, r.verb),
        }
        if t is not None:
            entry["task"] = f"{task_key(t.number)} {t.title}"
        elif r.entity_type == "section":
            entry["section"] = str(r.entity_id)
        fields = sorted(k for k in r.diff if k not in ("position", "parent_position"))
        if fields and r.verb == "task.updated":
            entry["fields"] = fields
            # A date that moved is the answer to "did anything slip", so say from what to what.
            moved = {
                k: {"from": r.diff[k][0], "to": r.diff[k][1]}
                for k in ("due_on", "start_on", "priority")
                if k in r.diff and isinstance(r.diff[k], list) and len(r.diff[k]) >= 2
            }
            if moved:
                entry["changes"] = moved
        entries.append(entry)
    return ToolResult.success(
        f"{len(entries)}{'+' if more else ''} change(s) in {project.name} "
        f"from {args.since.isoformat()} to {until.isoformat()}",
        {"project": project.name, "entries": entries, "more": more},
    )


# ---------------- list_people ----------------


class ListPeopleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, max_length=100, description="Part of a name or email")
    project: str | None = Field(
        default=None, max_length=200, description="Only explicit members of this project"
    )
    limit: int = Field(default=20, ge=1, le=50)


@tool(
    name="list_people",
    description="Find people in the workspace by name or email (to assign or mention them).",
    risk="read",
    scopes=READ,
)
async def list_people(tc: ToolContext, args: ListPeopleArgs) -> ToolResult:
    people: list[dict[str, Any]]
    if args.project:
        project, _ = await resolve_project(tc, args.project)
        q = (args.query or "").strip().lower()
        people = [
            {"id": str(u.id), "name": u.name, "email": u.email, "role": role}
            for u, role in await project_members(tc.session, project.id)
            if u.status != "disabled" and (not q or q in u.name.lower() or q in u.email.lower())
        ][: args.limit]
    else:
        people = [
            {"id": str(u.id), "name": u.name, "email": u.email}
            for u in await list_users(tc.session, tc.ctx, q=args.query, limit=args.limit)
        ]
    return ToolResult.success(f"{len(people)} people", {"people": people})


# ---------------- semantic_search ----------------


class SemanticSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(
        min_length=1, max_length=500, description="What to look for, in the user's own words"
    )
    types: list[Literal["task", "comment", "attachment", "project"]] | None = Field(
        default=None, description="Limit to some kinds of content; default: all"
    )
    limit: int = Field(default=8, ge=1, le=15)


@tool(
    name="semantic_search",
    description=(
        "Search tasks, comments, attached files and project briefs by meaning (not just exact "
        "words). Returns snippets with citations like [T-123] to quote in answers."
    ),
    risk="read",
    scopes=READ,
)
async def semantic_search(tc: ToolContext, args: SemanticSearchArgs) -> ToolResult:
    if tc.llm is None:
        raise ToolError("unavailable", "Semantic search isn't available here")
    hits = await retrieval.search(
        tc.session,
        tc.llm,
        tc.ctx,
        args.query,
        k=args.limit,
        types=tuple(args.types or INDEXED),
    )
    return ToolResult.success(
        f"{len(hits)} result(s)" if hits else "Nothing found for that",
        {"results": [h.to_json() for h in hits]},
    )


# ---------------- get_attachment_text (S5.1.5) ----------------

ATTACHMENT_TEXT_LIMIT = 20_000  # characters


async def _task_attachments(tc: ToolContext, task: Task) -> list[Attachment]:
    """Files on the task itself and on its comments (the caller already sees the task)."""
    rows = await tc.session.execute(
        select(Attachment)
        .outerjoin(Comment, Comment.id == Attachment.comment_id)
        .where(
            Attachment.deleted_at.is_(None),
            Attachment.is_current.is_(True),
            or_(
                Attachment.task_id == task.id,
                and_(Comment.task_id == task.id, Comment.deleted_at.is_(None)),
            ),
        )
        .order_by(Attachment.created_at, Attachment.id)
    )
    return list(rows.scalars())


class GetAttachmentTextArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: TaskRef
    name: str | None = Field(
        default=None, max_length=300, description="File name, or part of it; omit if only one"
    )


@tool(
    name="get_attachment_text",
    description=(
        "Plain text only of a file attached to a task (PDF, Word or text), cut at 20,000 "
        "characters. Prefer read_file (structure, tables, locators) and query_table (numbers)."
    ),
    risk="read",
    scopes=READ,
)
async def get_attachment_text(tc: ToolContext, args: GetAttachmentTextArgs) -> ToolResult:
    task, _, _ = await resolve_task(tc, args.task)
    files = await _task_attachments(tc, task)
    if args.name:
        wanted = args.name.strip().lower()
        exact = [a for a in files if a.filename.lower() == wanted]
        files = exact or [a for a in files if wanted in a.filename.lower()]
    key = task_key(task.number)
    if not files:
        return ToolResult.failure("not_found", f"No matching file on {key}")
    if len(files) > 1:
        return ToolResult.failure(
            "ambiguous",
            f"{len(files)} files on {key} match; say which one",
            candidates=[{"name": a.filename} for a in files[:8]],
        )
    att = files[0]
    if att.extract_status == "pending":
        return ToolResult.failure(
            "not_ready", f"{att.filename} is still being read; try again shortly"
        )
    if not att.text_extract:
        return ToolResult.failure(
            "no_text", f"No text could be read from {att.filename} ({att.mime})"
        )
    text = att.text_extract
    cut = len(text) > ATTACHMENT_TEXT_LIMIT
    return ToolResult.success(
        f"Read {att.filename} on {key}" + (" (first 20,000 characters)" if cut else ""),
        {
            "file": att.filename,
            "mime": att.mime,
            "text": text[:ATTACHMENT_TEXT_LIMIT],
            "truncated": cut,
        },
    )


# ---------------- get_portfolio (S6.2.2) ----------------


class GetPortfolioArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio: str | None = Field(
        default=None,
        max_length=200,
        description="Portfolio name or id; omit to list every portfolio",
    )


@tool(
    name="get_portfolio",
    description=(
        "Portfolios (named sets of projects): omit `portfolio` to list them; name one to get its "
        "projects with status, tasks done/total, overdue count, due date and latest update."
    ),
    risk="read",
    scopes=READ,
)
async def get_portfolio(tc: ToolContext, args: GetPortfolioArgs) -> ToolResult:
    s = tc.session
    listed = await portfolios.list_portfolios(s, tc.ctx)
    if args.portfolio is None:
        return ToolResult.success(
            f"{len(listed)} portfolios",
            {
                "portfolios": [
                    {"id": str(p.id), "name": p.name, "status": p.status, "projects": n}
                    for p, n in listed
                ]
            },
        )
    want = args.portfolio.strip().lower()
    exact = [p for p, _ in listed if str(p.id) == want or p.name.lower() == want]
    found = exact or [p for p, _ in listed if want in p.name.lower()]
    if not found:
        raise ToolError("not_found", f"No portfolio called {args.portfolio!r}")
    if len(found) > 1:
        raise ToolError(
            "ambiguous",
            "More than one portfolio matches",
            candidates=[{"id": str(p.id), "name": p.name} for p in found[:8]],
        )
    p = found[0]
    rows, hidden = await portfolios.portfolio_rows(s, tc.ctx, p)
    data: dict[str, Any] = {
        "id": str(p.id),
        "name": p.name,
        "status": p.status,
        "projects": [
            {
                "name": x.name,
                "status": x.status,
                "tasks_done": f["completed_tasks"],
                "tasks_total": f["total_tasks"],
                "overdue": f["overdue_tasks"],
                "due_on": iso(x.due_on) if x.due_on else None,
                "latest_update": clip(f["latest_update_title"], 200),
            }
            for x, f in rows
        ],
    }
    if hidden:
        data["projects_you_cannot_see"] = hidden
    return ToolResult.success(p.name, {"portfolio": data})


# ---------------- get_goals (S6.3.1) ----------------


class GetGoalsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str | None = Field(
        default=None, max_length=200, description="Goal name or id; omit to list every goal"
    )


def _pct(v: float | None) -> int | None:
    return None if v is None else round(v * 100)


@tool(
    name="get_goals",
    description=(
        "Goals: omit `goal` to list them (period, owner, status, progress %); name one to get its "
        "metric, how progress is measured, linked projects/portfolios and sub-goals."
    ),
    risk="read",
    scopes=READ,
)
async def get_goals(tc: ToolContext, args: GetGoalsArgs) -> ToolResult:
    s = tc.session
    all_goals, progress = await goals.list_goals(s, tc.ctx)
    names = await user_names(tc, {g.owner_id for g in all_goals})

    def brief(g: Any) -> dict[str, Any]:
        return {
            "id": str(g.id),
            "name": g.name,
            "period": g.period_label or f"{iso(g.period_start)}..{iso(g.period_end)}",
            "owner": names.get(g.owner_id),
            "status": g.status,
            "progress_pct": _pct(progress.by_goal.get(g.id)),
        }

    if args.goal is None:
        return ToolResult.success(
            f"{len(all_goals)} goals", {"goals": [brief(g) for g in all_goals]}
        )
    want = args.goal.strip().lower()
    exact = [g for g in all_goals if str(g.id) == want or g.name.lower() == want]
    found = exact or [g for g in all_goals if want in g.name.lower()]
    if not found:
        raise ToolError("not_found", f"No goal called {args.goal!r}")
    if len(found) > 1:
        raise ToolError(
            "ambiguous",
            "More than one goal matches",
            candidates=[{"id": str(g.id), "name": g.name} for g in found[:8]],
        )
    g = found[0]
    links, hidden = await goals.link_views(s, tc.ctx, g, progress)
    data = {
        **brief(g),
        "description": clip(g.description, 1000),
        "progress_source": g.progress_source,
        "metric": g.metric,
        "links": [
            {
                "type": x["entity_type"],
                "name": x["name"],
                "status": x["status"],
                "progress_pct": _pct(x["progress"]),
            }
            for x in links
        ],
        "sub_goals": [brief(c) for c in all_goals if c.parent_id == g.id],
    }
    if hidden:
        data["linked_projects_you_cannot_see"] = hidden
    return ToolResult.success(g.name, {"goal": data})


# ---------------- suggest_rebalance (S6.4.2) ----------------


class SuggestRebalanceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weeks: int = Field(default=4, ge=1, le=12, description="How many weeks from this one to fix")
    project: str | None = Field(
        default=None, max_length=200, description="Only move this project's work (name or id)"
    )


def _rebalance_call(r: Rebalance, mv: Move) -> dict[str, Any]:
    """The write-tool call that makes one move (Mo proposes these; nothing is changed here)."""
    key = mv.item.key
    if mv.kind == "reassign":
        assert mv.to_person is not None
        return {
            "tool": "update_task",
            "args": {"task": key, "assignee": r.people[mv.to_person].email},
        }
    if mv.kind == "start_later":
        return {"tool": "update_task", "args": {"task": key, "start_on": iso(mv.new_start)}}
    args: dict[str, Any] = {"task": key, "due_on": iso(mv.new_due)}
    if mv.new_start is not None:
        args["start_on"] = iso(mv.new_start)
    return {"tool": "reschedule_task", "args": args}


@tool(
    name="suggest_rebalance",
    description=(
        "Who is over capacity in the coming weeks and the moves that fix it, computed in code: "
        "give a task to someone with room and edit access, else start it later (same due date), "
        "else push it later (moves its due date; dependents follow). Changes nothing. To act, "
        "propose each move's `call` as given, all together, and say which moves change a due date."
    ),
    risk="read",
    scopes=READ,
)
async def suggest_rebalance(tc: ToolContext, args: SuggestRebalanceArgs) -> ToolResult:
    project_id = (await resolve_project(tc, args.project))[0].id if args.project else None
    today = today_for(tc.ctx)
    r = await rebalance.suggest(tc.session, tc.ctx, today, args.weeks, project_id, today=today)
    data: dict[str, Any] = {
        "status": r.status,
        "moves": [
            {
                "change": rebalance.describe(r, mv),
                "why": rebalance.why(r, mv),
                "changes_due_date": mv.due_moved,
                "call": _rebalance_call(r, mv),
            }
            for mv in r.moves
        ],
        "still_over": [
            {
                "person": r.people[u.person].name,
                "week_of": iso(u.week),
                "over": rebalance.hours(u.over),
                "reason": u.reason,
            }
            for u in r.unresolved
        ],
    }
    summary = {
        "balanced": f"{len(r.moves)} moves bring everyone under capacity",
        "partial": f"{len(r.moves)} moves help; {len(r.unresolved)} weeks stay over",
        "nothing_to_do": "Nobody is over capacity",
        "no_estimates": "No estimates yet: rebalancing works on hours",
    }[r.status]
    return ToolResult.success(summary, {"rebalance": data})


# ---------------- query_metrics (S6.5.2) ----------------


@tool(
    name="query_metrics",
    description=(
        "Count tasks the user can see, the way a dashboard chart does: filters (status, overdue, "
        "blocked, people, projects, sections, tags, priorities, due or completed within N days), "
        "optionally split by one dimension (group_by: assignee, section, project, status, "
        "priority, tag, or a single-select field) or over time (time_bucket day/week/month by "
        "completed, created or due date). measure sum_estimate gives estimated hours. The server "
        "computes every number: quote them as given. kind list returns the tasks themselves."
    ),
    risk="read",
    scopes=READ,
)
async def query_metrics(tc: ToolContext, args: chart.ChartFilters) -> ToolResult:
    try:
        r = await chart.resolve(tc.session, tc.ctx, args, None)
    except chart.Ask as ask:
        raise ToolError("unclear", ask.question) from None
    res = await dashboard_query.run(tc.session, tc.ctx, r.kind, r.spec)
    hours = res.measure == "sum_estimate"

    def num(v: float) -> float:
        return round(v / 60, 1) if hours else v

    data: dict[str, Any] = {
        "what": res.description,
        "unit": "hours" if hours else "tasks",
        "total": num(res.total),
        "tasks_matched": res.tasks_total,
    }
    if res.value is not None:
        data["value"] = num(res.value)
    if res.groups:
        data["groups"] = [{"label": g.label, "value": num(g.value)} for g in res.groups]
    if res.series:
        data["series"] = [
            {"from": iso(p.start), "to": iso(p.end), "value": num(p.value)} for p in res.series
        ]
    if res.tasks:
        data["tasks"] = [
            {"key": t.key, "title": t.title, "due_on": iso(t.due_on), "assignee": t.assignee_name}
            for t in res.tasks
        ]
        data["more"] = res.more
    if hours and res.unestimated:
        data["tasks_without_estimate"] = res.unestimated
    data["note"] = "Counts top-level tasks in projects the user can see."
    return ToolResult.success(res.description, {"metrics": data})


class ListMyAsksArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "answered", "expired", "all"] = "open"
    limit: int = Field(default=20, ge=1, le=50)


@tool(
    name="list_my_asks",
    description=(
        "Questions agents are waiting on the user to answer (oldest first): who asks, about which "
        "task, the question, its options or form fields, and when it expires. Read-only: Mo never "
        "answers an ask by itself."
    ),
    risk="read",
    scopes=READ,
)
async def list_my_asks(tc: ToolContext, args: ListMyAsksArgs) -> ToolResult:
    from momentum.domain.agents.models import Agent
    from momentum.domain.asks import service as asks

    if tc.ctx.actor.id is None or tc.ctx.actor.role == "guest":
        return ToolResult.success("0 question(s)", {"asks": []})
    rows = await asks.list_asks(
        tc.session, tc.ctx, mine=True, status=None if args.status == "all" else args.status
    )
    out = []
    for a in rows[: args.limit]:
        agent = await tc.session.get(Agent, a.agent_id)
        task = await tc.session.get(Task, a.task_id)
        item: dict[str, Any] = {
            "agent": agent.name if agent else None,
            "task": task_key(task.number) if task else None,
            "task_title": task.title if task else None,
            "question": a.title,
            "kind": a.kind,
            "status": a.status,
            "asked": iso(a.created_at),
            "expires": iso(a.expires_at),
        }
        if a.options:
            item["options"] = [o["label"] for o in a.options]
        if a.form:
            item["fields"] = [f["label"] for f in a.form]
        if a.body:
            item["details"] = clip(a.body, 400)
        out.append(item)
    return ToolResult.success(f"{len(out)} question(s)", {"asks": out})


TOOLS = [
    list_my_asks,
    search_tasks,
    semantic_search,
    get_task,
    get_project,
    get_portfolio,
    get_goals,
    suggest_rebalance,
    query_metrics,
    get_section_tasks,
    list_my_tasks,
    list_user_tasks,
    get_project_activity,
    list_people,
    get_attachment_text,
]
