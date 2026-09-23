from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_BATCH = 100


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


class TaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    section_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class TaskBatchCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titles: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    section_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None


class TaskPatchIn(BaseModel):
    """Partial update: only fields present are changed (null clears a nullable field)."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    assignee_id: uuid.UUID | None = None
    start_on: date | None = None
    due_on: date | None = None
    due_at: datetime | None = Field(
        default=None,
        description="Due time (timezone-aware). Setting it without due_on derives due_on in the "
        "actor's timezone; clearing due_on clears due_at.",
    )
