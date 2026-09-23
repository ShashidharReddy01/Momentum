from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from momentum.domain.teams.schemas import COLOR_PATTERN
from momentum.domain.users.schemas import UserOut

Privacy = Literal["team", "private"]
View = Literal["list", "board", "calendar", "timeline", "overview", "dashboard"]


class ProjectCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    privacy: Privacy = "team"
    color: str | None = Field(default=None, pattern=COLOR_PATTERN)


class ProjectPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    color: str | None = Field(default=None, pattern=COLOR_PATTERN)
    privacy: Privacy | None = None
    default_view: View | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    name: str
    color: str | None
    privacy: str
    default_view: str
    status: str | None
    archived_at: datetime | None
    owner_id: uuid.UUID | None
    my_role: str
    is_favorite: bool
    version: int


class ProjectMemberOut(BaseModel):
    user: UserOut
    role: str


class SectionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    position: str


class ProjectDetailOut(ProjectOut):
    team_name: str
    members: list[ProjectMemberOut]
    sections: list[SectionBrief]


class FavoriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


ProjectRoleName = Literal["admin", "editor", "commenter", "viewer"]


class ProjectMemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    role: ProjectRoleName = "editor"


class ProjectMemberPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: ProjectRoleName
