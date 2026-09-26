from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["on_track", "at_risk", "off_track", "on_hold", "complete"]


class StatusItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)


class StatusSections(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed: list[StatusItem] = Field(default_factory=list, max_length=30)
    slipped: list[StatusItem] = Field(default_factory=list, max_length=30)
    blockers: list[StatusItem] = Field(default_factory=list, max_length=30)
    next: list[StatusItem] = Field(default_factory=list, max_length=30)


class StatusUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=4000)
    sections: StatusSections = Field(default_factory=StatusSections)
    generated_by_ai: bool = Field(
        default=False, description="The text started as Mo's draft (shown with the AI mark)"
    )


class StatusCitationOut(BaseModel):
    ref: str
    type: Literal["task", "project"]
    valid: bool
    id: str | None = None
    key: str | None = None
    title: str | None = None


class StatusUpdateOut(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    status: Status
    title: str
    summary: str
    sections: StatusSections
    author_id: uuid.UUID | None
    generated_by_ai: bool
    created_at: datetime
    citations: list[StatusCitationOut] = Field(default_factory=list)
