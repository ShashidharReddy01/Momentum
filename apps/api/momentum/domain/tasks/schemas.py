from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_BATCH = 100
Priority = Literal["urgent", "high", "medium", "low"]


class RecurrenceIn(BaseModel):
    """A repeat rule, stored as given (S3.2.1). Generating the next occurrence is Phase 4."""

    model_config = ConfigDict(extra="forbid")
    freq: Literal["daily", "weekly", "monthly", "yearly"]
    interval: int = Field(default=1, ge=1, le=99)
    by_weekday: list[int] | None = Field(
        default=None, description="0 = Monday … 6 = Sunday (weekly rules)"
    )
    workdays_only: bool = False
    text: str | None = Field(default=None, max_length=100, description="As the user wrote it")


class TaskOut(BaseModel):
    id: uuid.UUID
    number: int
    key: str
    title: str
    type: str
    project_id: uuid.UUID | None
    section_id: uuid.UUID | None
    position: str | None
    assignee_id: uuid.UUID | None
    start_on: date | None
    due_on: date | None
    due_at: datetime | None
    completed_at: datetime | None
    parent_id: uuid.UUID | None
    priority: str | None
    version: int
    created_at: datetime
    subtask_count: int = 0
    completed_subtask_count: int = 0


class TaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    section_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    due_on: date | None = None
    due_at: datetime | None = None
    priority: Priority | None = None
    recurrence: RecurrenceIn | None = None


class TaskBatchCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titles: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    section_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None


class TaskPatchIn(BaseModel):
    """Partial update: only fields present are changed (null clears a nullable field)."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: dict[str, Any] | None = Field(
        default=None, description="Rich text (Tiptap JSON); null clears it"
    )
    description_base: str | None = Field(
        default=None,
        max_length=64,
        description="description_hash the edit started from; a mismatch returns 409",
    )
    assignee_id: uuid.UUID | None = None
    start_on: date | None = None
    due_on: date | None = None
    due_at: datetime | None = Field(
        default=None,
        description="Due time (timezone-aware). Setting it without due_on derives due_on in the "
        "actor's timezone; clearing due_on clears due_at.",
    )
    priority: Priority | None = None


class TaskFieldsIn(BaseModel):
    """Fields that can be set on many tasks at once."""

    model_config = ConfigDict(extra="forbid")
    assignee_id: uuid.UUID | None = None
    start_on: date | None = None
    due_on: date | None = None
    due_at: datetime | None = None
    priority: Priority | None = None


class TaskMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_id: uuid.UUID
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class TaskConvertIn(BaseModel):
    """Convert a task to a milestone, or back (S2.4.3)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["task", "milestone"]


class TaskBulkIn(BaseModel):
    """One action on many tasks, all-or-nothing, undoable as one batch.

    ``move`` keeps the tasks' current relative order and places them consecutively."""

    model_config = ConfigDict(extra="forbid")
    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["update", "move", "complete", "uncomplete", "delete"]
    patch: TaskFieldsIn | None = None
    section_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class NamedRef(BaseModel):
    id: uuid.UUID
    name: str


class ProjectRef(NamedRef):
    color: str | None


class TaskDetailOut(TaskOut):
    """A task with everything the task pane needs."""

    parent: NamedRef | None = None
    followers: list[uuid.UUID] = Field(default_factory=list)
    my_role: str | None = Field(
        default=None, description="The caller's access: admin, editor, commenter or viewer"
    )
    description: dict[str, Any] | None
    description_hash: str
    recurrence: dict[str, Any] | None = Field(
        default=None, description="Repeat rule (stored; generating occurrences is Phase 4)"
    )
    project: ProjectRef | None
    section: NamedRef | None
    created_by: uuid.UUID | None
    completed_by: uuid.UUID | None
    updated_at: datetime


class SubtaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class SubtaskMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class FollowerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID


class FollowersOut(BaseModel):
    followers: list[uuid.UUID]


class TaskProjectOut(BaseModel):
    """One of a task's placements (S2.4.1 multi-homing): which project, which section, where."""

    project: ProjectRef
    section: NamedRef
    position: str


class TaskProjectAddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    section_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class OtherPlacementOut(BaseModel):
    """One task's placement in a project other than the one being listed — the shape the bulk
    per-project endpoint returns, for list-row "also in" chips."""

    task_id: uuid.UUID
    project: ProjectRef


class TaskSummaryOut(BaseModel):
    """Just enough of a task to show it in a "blocked by" / "blocking" list (S2.4.2)."""

    id: uuid.UUID
    key: str
    title: str
    completed_at: datetime | None


class DependenciesOut(BaseModel):
    blocked_by: list[TaskSummaryOut]
    blocking: list[TaskSummaryOut]


class DependencyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    depends_on_id: uuid.UUID


class BlockedTaskOut(BaseModel):
    """One task id with an incomplete blocker — the shape the bulk per-project endpoint returns,
    for the list row's "waiting on" icon."""

    task_id: uuid.UUID
