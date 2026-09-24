from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

_COLOR = r"^#[0-9a-fA-F]{6}$"


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    color: str


class TagCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
    color: Annotated[str, StringConstraints(pattern=_COLOR)] = "#94a3b8"


class TagPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=50)
    color: Annotated[str, StringConstraints(pattern=_COLOR)] | None = None


class TaskTagIn(BaseModel):
    """Attach an existing tag, or create one inline by name (whichever the client has)."""

    model_config = ConfigDict(extra="forbid")
    tag_id: uuid.UUID | None = None
    name: (
        Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)] | None
    ) = None


class TaskTagOut(BaseModel):
    """One task's tag — the shape the bulk per-project endpoint returns."""

    model_config = ConfigDict(from_attributes=True)
    task_id: uuid.UUID
    tag: TagOut
