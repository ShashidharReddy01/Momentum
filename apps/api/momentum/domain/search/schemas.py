from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

SearchType = Literal["task", "project", "person", "comment"]
ALL_TYPES: tuple[SearchType, ...] = ("task", "project", "person", "comment")


class TaskHit(BaseModel):
    id: uuid.UUID
    title: str
    type: str
    completed_at: str | None
    project_id: uuid.UUID | None
    project_name: str | None


class ProjectHit(BaseModel):
    id: uuid.UUID
    name: str
    color: str | None


class PersonHit(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    avatar_url: str | None


class CommentHit(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    task_title: str
    snippet: str


class SearchResultsOut(BaseModel):
    tasks: list[TaskHit]
    projects: list[ProjectHit]
    people: list[PersonHit]
    comments: list[CommentHit]
