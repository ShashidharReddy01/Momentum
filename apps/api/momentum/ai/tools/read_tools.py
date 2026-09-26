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

from momentum.ai.tools.base import ToolContext, ToolError, ToolResult, tool
from momentum.ai.tools.refs import (
    TaskRef,
    resolve_person,
    resolve_project,
    resolve_section,
    resolve_task,
)
from momentum.ai.tools.views import clip, iso, task_brief, task_briefs, user_names
from momentum.core.activity import Activity
from momentum.core.ids import task_key
from momentum.domain.access import visible_projects_clause
from momentum.domain.comments.models import Comment
from momentum.domain.mytasks.service import list_my_tasks as svc_list_my_tasks
from momentum.domain.projects.models import Project
from momentum.domain.projects.service import project_members
from momentum.domain.sections.models import Section
from momentum.domain.sections.service import list_sections
from momentum.domain.tasks.models import Task, TaskDependency, TaskProject
from momentum.domain.tasks.service import today_for
from momentum.domain.teams.models import Team
from momentum.domain.users.service import list_users

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
    limit: int = Field(default=20, ge=1, le=50)


@tool(
    name="search_tasks",
    description=(
        "Find tasks the user can see with structured filters (text, project, assignee, status, "
        "due range, overdue). Returns keys like T-123 to use with other tools."
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
    if task.description_text:
        detail["description"] = clip(task.description_text)
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
                .where(TaskDependency.task_id == task.id, Task.deleted_at.is_(None))
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
    if project.due_on is not None:
        data["due_on"] = iso(project.due_on)
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


TOOLS = [
    search_tasks,
    get_task,
    get_project,
    get_section_tasks,
    list_my_tasks,
    list_user_tasks,
    get_project_activity,
    list_people,
]
