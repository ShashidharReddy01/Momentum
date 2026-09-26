"""Write tools (risk ``low`` / ``medium`` / ``high``): each is a thin adapter over domain services,
so validation, permissions, activity, undo payloads and outbox events are exactly the UI's.

Every write tool passes ``tc.batch_id`` to the services that accept one; the registry stamps the
same batch on anything else the call recorded, so one tool call is one undo.

``semantic_search`` is a read tool (``read_tools.py``, S3.1.4); ``create_status_update`` is
registered by S3.4.3 (it needs the ``status_updates`` table). Priority became settable in S3.2.1,
when the task service started writing it.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from momentum.ai.tools.base import ToolContext, ToolError, ToolResult, tool
from momentum.ai.tools.refs import (
    TaskRef,
    resolve_person,
    resolve_project,
    resolve_section,
    resolve_task,
    resolve_team,
)
from momentum.ai.tools.views import target, task_brief
from momentum.core.ids import task_key
from momentum.domain.comments.service import create_comment
from momentum.domain.projects.schemas import ProjectCreateIn
from momentum.domain.projects.service import create_project
from momentum.domain.sections.service import create_section, list_sections, rename_section
from momentum.domain.tasks import service as tasks
from momentum.domain.tasks.models import Task
from momentum.domain.teams.models import Team, TeamMember

WRITE = ("tasks:write",)
CLEAR_WORDS = {"none", "nobody", "unassigned", "no one"}


def text_doc(text: str) -> dict[str, Any]:
    """Plain text (as a model writes it) → a rich-text document: one paragraph per line."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in lines
            if line
        ],
    }


def _created(tc: ToolContext, brief: dict[str, Any]) -> dict[str, Any]:
    """A created entity as reported to the model. A preview's ids and keys are placeholders
    that won't exist, so they are left out (the model must not reference them)."""
    if tc.preview:
        return {k: v for k, v in brief.items() if k not in ("id", "key")}
    return brief


def _new_target(title: str) -> dict[str, Any]:
    return {"type": "task", "new": True, "title": title}


class _TaskFields(BaseModel):
    """Optional task fields shared by the create/update tools. Only fields that are given are
    applied; ``null`` clears a field (for the assignee, "none" does too)."""

    model_config = ConfigDict(extra="forbid")
    assignee: str | None = Field(
        default=None, max_length=200, description='A name, email, "me", or "none" to unassign'
    )
    start_on: date | None = None
    due_on: date | None = None
    priority: Literal["urgent", "high", "medium", "low"] | None = None
    description: str | None = Field(
        default=None, max_length=20_000, description="Plain text; replaces the description"
    )

    async def to_patch(self, tc: ToolContext) -> dict[str, Any]:
        given = self.model_fields_set
        patch: dict[str, Any] = {}
        if "assignee" in given:
            if self.assignee is None or self.assignee.strip().lower() in CLEAR_WORDS:
                patch["assignee_id"] = None
            else:
                patch["assignee_id"] = (await resolve_person(tc, self.assignee)).id
        for f in ("start_on", "due_on", "priority"):
            if f in given:
                patch[f] = getattr(self, f)
        if "description" in given:
            patch["description"] = text_doc(self.description) if self.description else None
        return patch


# ---------------- create_task ----------------


class CreateTaskArgs(_TaskFields):
    project: str = Field(max_length=200, description="Project name or id")
    title: str = Field(min_length=1, max_length=500)
    section: str | None = Field(
        default=None, max_length=200, description="Section name or id; default: the first one"
    )


@tool(
    name="create_task",
    description="Create a task in a project (optionally in a section, assigned and dated).",
    risk="low",
    scopes=WRITE,
)
async def create_task(tc: ToolContext, args: CreateTaskArgs) -> ToolResult:
    s, ctx = tc.session, tc.ctx
    project, _ = await resolve_project(tc, args.project)
    section = await resolve_section(tc, project.id, args.section) if args.section else None
    patch = await args.to_patch(tc)
    m = await tasks.create_task(
        s,
        ctx,
        project.id,
        args.title,
        section_id=section.id if section else None,
        assignee_id=patch.pop("assignee_id", None),
        due_on=patch.pop("due_on", None),
        batch_id=tc.batch_id,
    )
    task, _ = m.entity
    patch = {k: v for k, v in patch.items() if v is not None}
    if patch:
        await tasks.update_task(s, ctx, task.id, patch, batch_id=tc.batch_id)
    brief = _created(tc, await task_brief(tc, task))
    return ToolResult.success(
        f'{tc.verb("Created", "Would create")} "{task.title}" in {project.name}',
        {"task": brief},
        targets=[_new_target(task.title)],
    )


# ---------------- update_task ----------------


class UpdateTaskArgs(_TaskFields):
    task: TaskRef
    title: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _something(self) -> UpdateTaskArgs:
        if not (self.model_fields_set - {"task"}):
            raise ValueError("give at least one field to change")
        return self


@tool(
    name="update_task",
    description=(
        "Change fields of a task the user can edit: title, assignee, start/due dates, "
        "priority, description. Omit fields to keep them; null clears one."
    ),
    risk="low",
    scopes=WRITE,
)
async def update_task(tc: ToolContext, args: UpdateTaskArgs) -> ToolResult:
    task, _, _ = await resolve_task(tc, args.task)
    patch = await args.to_patch(tc)
    if "title" in args.model_fields_set:
        if args.title is None:
            raise ToolError("invalid_arguments", "A task needs a title")
        patch["title"] = args.title
    m = await tasks.update_task(tc.session, tc.ctx, task.id, patch, batch_id=tc.batch_id)
    key = task_key(task.number)
    if m.activity_id is None:
        return ToolResult.success(f"{key} already has those values", {"task": key})
    return ToolResult.success(
        f"{tc.verb('Updated', 'Would update')} {key} {task.title}",
        {"task": await task_brief(tc, m.entity)},
        targets=[target(task)],
    )


# ---------------- complete_task ----------------


class CompleteTaskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: TaskRef
    completed: bool = Field(default=True, description="false reopens a completed task")
    ignore_blockers: bool = Field(
        default=False,
        description="Complete even if tasks it waits on are open (only if the user said so)",
    )


@tool(
    name="complete_task",
    description="Mark a task complete (or reopen it).",
    risk="low",
    scopes=WRITE,
)
async def complete_task(tc: ToolContext, args: CompleteTaskArgs) -> ToolResult:
    task, _, _ = await resolve_task(tc, args.task)
    m = await tasks.set_completed(
        tc.session,
        tc.ctx,
        task.id,
        args.completed,
        batch_id=tc.batch_id,
        force=args.ignore_blockers,
    )
    key = task_key(task.number)
    if m.activity_id is None:
        state = "complete" if args.completed else "open"
        return ToolResult.success(f"{key} is already {state}", {"task": key})
    done = (
        tc.verb("Completed", "Would complete")
        if args.completed
        else tc.verb("Reopened", "Would reopen")
    )
    return ToolResult.success(f"{done} {key} {task.title}", targets=[target(task)])


# ---------------- move_task ----------------


class MoveTaskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: TaskRef
    section: str | None = Field(
        default=None, max_length=200, description="Target section name or id"
    )
    project: str | None = Field(
        default=None,
        max_length=200,
        description="Target project, to move the task to another project",
    )

    @model_validator(mode="after")
    def _somewhere(self) -> MoveTaskArgs:
        if self.section is None and self.project is None:
            raise ValueError("give a section, a project, or both")
        return self


@tool(
    name="move_task",
    description=(
        "Move a top-level task to another section, or to another project (at the end of the "
        "section, the first section by default)."
    ),
    risk="low",
    scopes=WRITE,
)
async def move_task(tc: ToolContext, args: MoveTaskArgs) -> ToolResult:
    s, ctx = tc.session, tc.ctx
    task, placement, _ = await resolve_task(tc, args.task)
    if placement is None or task.parent_id is not None:
        raise ToolError("not_movable", "Only top-level project tasks can be moved")
    key = task_key(task.number)
    if args.project is not None:
        dest, _ = await resolve_project(tc, args.project)
    else:
        dest, _ = await resolve_project(tc, str(placement.project_id))
    section = (
        await resolve_section(tc, dest.id, args.section)
        if args.section
        else (await list_sections(s, dest.id))[0]
    )
    if dest.id == placement.project_id:
        if section.id == placement.section_id:
            return ToolResult.success(f"{key} is already in {section.name}", {"task": key})
        await tasks.move_tasks(s, ctx, [task.id], section_id=section.id, batch_id=tc.batch_id)
    else:
        # another project: place it there, then take it out of the old one (two undoable steps,
        # one batch). Multi-homed tasks leave only the placement they were found through.
        await tasks.add_task_to_project(s, ctx, task.id, dest.id, section_id=section.id)
        await tasks.remove_task_from_project(s, ctx, task.id, placement.project_id)
    return ToolResult.success(
        f"{tc.verb('Moved', 'Would move')} {key} {task.title} to {dest.name} / {section.name}",
        targets=[target(task)],
    )


# ---------------- add_comment ----------------


class AddCommentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: TaskRef
    text: str = Field(min_length=1, max_length=5000, description="Plain text")


@tool(
    name="add_comment",
    description="Add a comment to a task. It is shown as written by AI on the user's behalf.",
    risk="low",
    scopes=WRITE,
)
async def add_comment(tc: ToolContext, args: AddCommentArgs) -> ToolResult:
    task, _, _ = await resolve_task(tc, args.task)
    await create_comment(tc.session, tc.ctx, task.id, text_doc(args.text))
    key = task_key(task.number)
    return ToolResult.success(
        f"{tc.verb('Commented', 'Would comment')} on {key} {task.title}",
        targets=[target(task)],
    )


# ---------------- create_subtasks ----------------


class SubtaskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    assignee: str | None = Field(default=None, max_length=200, description="A name, email or me")
    due_on: date | None = None


class CreateSubtasksArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent: TaskRef
    subtasks: list[SubtaskItem] = Field(min_length=1, max_length=20)


@tool(
    name="create_subtasks",
    description="Create several subtasks under a task, in order (optionally assigned and dated).",
    risk="low",
    scopes=WRITE,
)
async def create_subtasks(tc: ToolContext, args: CreateSubtasksArgs) -> ToolResult:
    s, ctx = tc.session, tc.ctx
    parent, _, _ = await resolve_task(tc, args.parent)
    created: list[Task] = []
    prev: uuid.UUID | None = None
    for item in args.subtasks:
        m = await tasks.create_subtask(
            s, ctx, parent.id, item.title, after_id=prev, batch_id=tc.batch_id
        )
        sub = m.entity
        patch: dict[str, Any] = {}
        if item.assignee:
            patch["assignee_id"] = (await resolve_person(tc, item.assignee)).id
        if item.due_on:
            patch["due_on"] = item.due_on
        if patch:
            await tasks.update_task(s, ctx, sub.id, patch, batch_id=tc.batch_id)
        created.append(sub)
        prev = sub.id
    key = task_key(parent.number)
    briefs = [_created(tc, b) for b in [await task_brief(tc, t) for t in created]]
    return ToolResult.success(
        f"{tc.verb('Created', 'Would create')} {len(created)} subtask(s) under {key}",
        {"parent": key, "subtasks": briefs},
        targets=[_new_target(t.title) for t in created],
    )


# ---------------- create_project_from_plan ----------------


class PlanTask(_TaskFields):
    title: str = Field(min_length=1, max_length=500)


class PlanSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    tasks: list[PlanTask] = Field(default_factory=list, max_length=100)


class CreateProjectFromPlanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    team: str | None = Field(
        default=None, max_length=200, description="Team name; default: the user's only team"
    )
    privacy: Literal["team", "private"] = "team"
    sections: list[PlanSection] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _size(self) -> CreateProjectFromPlanArgs:
        if sum(len(sec.tasks) for sec in self.sections) > 200:
            raise ValueError("a plan can have at most 200 tasks")
        return self


async def _default_team(tc: ToolContext) -> Team:
    teams = list(
        (
            await tc.session.execute(
                select(Team)
                .join(TeamMember, TeamMember.team_id == Team.id)
                .where(
                    TeamMember.user_id == tc.ctx.actor.id,
                    Team.workspace_id == tc.ctx.workspace_id,
                    Team.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if len(teams) == 1:
        return teams[0]
    if not teams:
        raise ToolError("not_found", "You aren't in any team, so a project can't be created")
    raise ToolError(
        "ambiguous",
        "You are in several teams; ask the user which team the project belongs to",
        candidates=[{"id": str(t.id), "name": t.name} for t in teams],
    )


@tool(
    name="create_project_from_plan",
    description=(
        "Create a new project with sections and tasks (assignees, dates, descriptions) from a "
        "plan. The user becomes its admin."
    ),
    risk="medium",
    scopes=("projects:write", "tasks:write"),
)
async def create_project_from_plan(tc: ToolContext, args: CreateProjectFromPlanArgs) -> ToolResult:
    s, ctx = tc.session, tc.ctx
    team = await resolve_team(tc, args.team) if args.team else await _default_team(tc)
    m = await create_project(
        s, ctx, ProjectCreateIn(team_id=team.id, name=args.name, privacy=args.privacy)
    )
    project = m.entity
    (first,) = await list_sections(s, project.id)  # a new project has one default section
    if first.name != args.sections[0].name.strip():
        await rename_section(s, ctx, first.id, args.sections[0].name)
    section_ids = [first.id]
    for sec in args.sections[1:]:
        created = await create_section(s, ctx, project.id, sec.name, after_id=section_ids[-1])
        section_ids.append(created.entity.id)
    titles: list[str] = []
    for sec, section_id in zip(args.sections, section_ids, strict=True):
        for item in sec.tasks:
            patch = await item.to_patch(tc)
            tm = await tasks.create_task(
                s,
                ctx,
                project.id,
                item.title,
                section_id=section_id,
                assignee_id=patch.pop("assignee_id", None),
                due_on=patch.pop("due_on", None),
                batch_id=tc.batch_id,
            )
            patch = {k: v for k, v in patch.items() if v is not None}
            if patch:
                await tasks.update_task(s, ctx, tm.entity[0].id, patch, batch_id=tc.batch_id)
            titles.append(item.title)
    data: dict[str, Any] = {
        "project": project.name,
        "team": team.name,
        "sections": [{"name": sec.name, "tasks": len(sec.tasks)} for sec in args.sections],
    }
    if not tc.preview:
        data["project_id"] = str(project.id)
    return ToolResult.success(
        f"{tc.verb('Created', 'Would create')} project {project.name} with "
        f"{len(args.sections)} section(s) and {len(titles)} task(s)",
        data,
        targets=[{"type": "project", "new": True, "title": project.name}],
    )


# ---------------- bulk_update_tasks ----------------


class BulkUpdateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[TaskRef] = Field(min_length=1, max_length=100)
    assignee: str | None = Field(
        default=None, max_length=200, description='A name, email, "me", or "none" to unassign'
    )
    start_on: date | None = None
    due_on: date | None = None
    priority: Literal["urgent", "high", "medium", "low"] | None = None
    completed: bool | None = Field(default=None, description="true completes, false reopens")

    @model_validator(mode="after")
    def _something(self) -> BulkUpdateArgs:
        if not (self.model_fields_set - {"tasks"}):
            raise ValueError("give at least one change")
        return self


@tool(
    name="bulk_update_tasks",
    description=(
        "Apply the same change (assignee, dates, priority, completed) to several tasks at once. "
        "All or "
        "nothing. More than 25 tasks needs the user's explicit confirmation."
    ),
    risk="medium",
    scopes=WRITE,
    bulk_limit=25,
)
async def bulk_update_tasks(tc: ToolContext, args: BulkUpdateArgs) -> ToolResult:
    s, ctx = tc.session, tc.ctx
    found: dict[uuid.UUID, Task] = {}
    for ref in args.tasks:
        task, _, _ = await resolve_task(tc, ref)
        found.setdefault(task.id, task)
    fields = _TaskFields.model_validate(
        {
            k: getattr(args, k)
            for k in args.model_fields_set
            if k in ("assignee", "start_on", "due_on", "priority")
        }
    )
    patch = await fields.to_patch(tc)
    changed = 0
    for task in found.values():
        hit = False
        # Completion first: undo runs a batch newest-first, and the "tasks.update" undo only
        # applies while the task is still at the version its edit produced. A completion
        # recorded after the edit would bump that version and make the batch un-undoable.
        if args.completed is not None:
            # like the bulk bar: no per-task "it has open blockers" prompt across a selection
            m = await tasks.set_completed(
                s, ctx, task.id, args.completed, batch_id=tc.batch_id, force=True
            )
            hit = m.activity_id is not None
        if patch:
            u = await tasks.update_task(s, ctx, task.id, patch, batch_id=tc.batch_id)
            hit = hit or u.activity_id is not None
        changed += int(hit)
    keys = [task_key(t.number) for t in found.values()]
    return ToolResult.success(
        f"{tc.verb('Updated', 'Would update')} {changed} of {len(found)} task(s)",
        {"tasks": keys, "changed": changed},
        targets=[target(t) for t in found.values()],
    )


# ---------------- delete_task ----------------


class DeleteTaskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: TaskRef


@tool(
    name="delete_task",
    description="Delete a task (it can be restored with undo). Always confirmed by the user.",
    risk="high",
    scopes=WRITE,
)
async def delete_task(tc: ToolContext, args: DeleteTaskArgs) -> ToolResult:
    task, _, _ = await resolve_task(tc, args.task)
    await tasks.delete_task(tc.session, tc.ctx, task.id, batch_id=tc.batch_id)
    key = task_key(task.number)
    return ToolResult.success(
        f"{tc.verb('Deleted', 'Would delete')} {key} {task.title}", targets=[target(task)]
    )


TOOLS = [
    create_task,
    update_task,
    complete_task,
    move_task,
    add_comment,
    create_subtasks,
    create_project_from_plan,
    bulk_update_tasks,
    delete_task,
]
