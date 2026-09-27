"""S4.3.1/S4.3.2: templates. A project template's payload captures sections, tasks (and their
subtasks) with dates relative to a chosen start date, assignees replaced by "roles" (so the
template doesn't depend on specific people), the fields it used, and its rules. Nothing here is
free-form JSON from the caller: the payload is always built server-side from a real project by
``service.save_project_template`` and only ever replayed by ``service.create_project_from_template``
— the schemas below are the API's read/write shapes around that, not a payload the client sends."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from momentum.domain.projects.schemas import Privacy
from momentum.domain.teams.schemas import COLOR_PATTERN

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class SaveProjectTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    name: Name
    description: Description | None = None


class RoleMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_id: str
    user_id: uuid.UUID | None = None


class NewProjectFromTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team_id: uuid.UUID
    name: Name
    start_date: date
    privacy: Privacy = "team"
    color: str | None = Field(default=None, pattern=COLOR_PATTERN)
    role_mapping: list[RoleMapping] = Field(default_factory=list, max_length=100)


class NewProjectOut(BaseModel):
    """Just enough for the caller to navigate to the new project — its own detail comes from
    the ordinary `GET /projects/{id}` (one write path, no second project-rendering shape)."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID | None
    kind: str
    name: str
    description: str | None
    payload: dict[str, Any]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
