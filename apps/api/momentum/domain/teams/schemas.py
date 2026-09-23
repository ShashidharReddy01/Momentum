from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from momentum.domain.users.schemas import UserOut

COLOR_PATTERN = r"^proj-(1[0-2]|[1-9])$"


class TeamCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, pattern=COLOR_PATTERN)


class TeamPatchIn(BaseModel):
    """Partial update: only fields present in the request are changed."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, pattern=COLOR_PATTERN)


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    color: str | None
    my_role: str | None
    member_count: int
    version: int


class TeamMemberOut(BaseModel):
    user: UserOut
    role: str


class TeamDetailOut(TeamOut):
    members: list[TeamMemberOut]


class TeamMemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    role: str = Field(default="member", pattern=r"^(lead|member)$")


class TeamMemberPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern=r"^(lead|member)$")
