from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReactionOut(BaseModel):
    emoji: str
    user_ids: list[uuid.UUID]


class CommentOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    author_id: uuid.UUID | None
    body: dict[str, Any]
    is_ai: bool
    created_at: datetime
    edited_at: datetime | None
    reactions: list[ReactionOut]
    can_edit: bool
    can_delete: bool


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: dict[str, Any] = Field(description="Rich text (Tiptap JSON); mention nodes notify people")


class ReactionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emoji: str = Field(max_length=16)
    active: bool = True


class MentionUser(BaseModel):
    id: uuid.UUID
    name: str
    email: str


class MentionTask(BaseModel):
    id: uuid.UUID
    title: str
    key: str


class MentionProject(BaseModel):
    id: uuid.UUID
    name: str
    color: str | None


class MentionSearchOut(BaseModel):
    users: list[MentionUser]
    tasks: list[MentionTask]
    projects: list[MentionProject]


class FeedSubject(BaseModel):
    id: uuid.UUID
    title: str


class ActivityItemOut(BaseModel):
    id: uuid.UUID
    verb: str
    actor_id: uuid.UUID | None
    actor_kind: str
    created_at: datetime
    changes: dict[str, list[Any]]
    subject: FeedSubject | None = Field(
        default=None, description="Set when the entry is about a subtask of this task"
    )


class FeedItemOut(BaseModel):
    kind: str = Field(description="comment | activity")
    at: datetime
    comment: CommentOut | None = None
    activity: ActivityItemOut | None = None


class FeedOut(BaseModel):
    data: list[FeedItemOut]
    truncated: bool
