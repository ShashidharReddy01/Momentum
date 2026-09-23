from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class SectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    position: str
    version: int


class SectionCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class SectionPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class SectionMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None
