from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

SearchType = Literal["task", "project", "person", "comment", "file"]
ALL_TYPES: tuple[SearchType, ...] = ("task", "project", "person", "comment", "file")


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


class FileHit(BaseModel):
    """Phase 7.5: a file matched by name or extracted text."""

    id: uuid.UUID
    filename: str
    kind: str
    project_id: uuid.UUID | None
    project_name: str | None
    task_id: uuid.UUID | None
    task_title: str | None


class SearchResultsOut(BaseModel):
    tasks: list[TaskHit]
    projects: list[ProjectHit]
    people: list[PersonHit]
    comments: list[CommentHit]
    files: list[FileHit] = []
