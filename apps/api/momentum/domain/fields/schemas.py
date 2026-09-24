from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from momentum.domain.fields.models import FIELD_TYPES

FieldType = Literal[
    "text",
    "number",
    "single_select",
    "multi_select",
    "date",
    "people",
    "checkbox",
    "url",
    "currency",
    "percent",
]
assert set(get_args(FieldType)) == set(
    FIELD_TYPES
)  # kept in sync with the model's check constraint

_COLOR = r"^#[0-9a-fA-F]{6}$"


class SelectOptionIn(BaseModel):
    """An option offered when creating/editing a single_select or multi_select field. ``id`` is
    omitted for a new option (the server assigns one) and required to edit or keep an existing
    one — options not repeated in a PATCH are dropped, same as a full replace."""

    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    label: Annotated[str, StringConstraints(min_length=1, max_length=80, strip_whitespace=True)]
    color: Annotated[str, StringConstraints(pattern=_COLOR)] = "#94a3b8"
    archived: bool = False


class SelectOptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    label: str
    color: str
    archived: bool


class NumberOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    precision: int = Field(default=0, ge=0, le=6)
    unit: str | None = Field(default=None, max_length=20)


class FieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    type: FieldType
    options: list[SelectOptionOut] | NumberOptions | None = None
    description: str | None
    is_library: bool
    created_by: uuid.UUID | None


class FieldCreateIn(BaseModel):
    """Create a brand-new field def (attached to a project by the endpoint it's posted to)."""

    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
    type: FieldType
    options: list[SelectOptionIn] | NumberOptions | None = None
    description: str | None = Field(default=None, max_length=500)
    is_library: bool = True


class FieldAttachIn(BaseModel):
    """Attach an existing library field to a project."""

    model_config = ConfigDict(extra="forbid")
    field_id: uuid.UUID
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class FieldPatchIn(BaseModel):
    """Edit a field def's name/description/options. Present-but-empty ``options`` clears them
    (only meaningful for select types, where it means "delete every option")."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    options: list[SelectOptionIn] | NumberOptions | None = None


class ProjectFieldOut(BaseModel):
    """A field as attached to one project: its definition plus this project's position/
    visibility."""

    model_config = ConfigDict(from_attributes=True)
    field: FieldOut
    position: str
    is_visible: bool


class ProjectFieldMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class ProjectFieldVisibilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_visible: bool


class FieldValueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any | None = None


class FieldValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    field_id: uuid.UUID
    value: Any | None


class TaskFieldValueOut(BaseModel):
    """One task's value for one field — the shape `list_project_field_values` returns in bulk."""

    model_config = ConfigDict(from_attributes=True)
    task_id: uuid.UUID
    field_id: uuid.UUID
    value: Any | None
