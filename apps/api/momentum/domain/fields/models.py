from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

POSITION = String(64, collation="C")

# Field types per docs/architecture/data-model.md §4.
FIELD_TYPES = (
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
)


class FieldDef(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A custom field definition, shared at the workspace level. ``is_library`` marks it as
    offered when adding a field to *another* project; a non-library field was created for one
    project only but still lives at the workspace level (so nothing else has to change if that
    project later wants to share it)."""

    __tablename__ = "field_defs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20))
    # single_select/multi_select: [{id, label, color, archived}]; number/currency/percent:
    # {precision, unit?}. Null for text/date/people/checkbox/url.
    options: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_library: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    __table_args__ = (CheckConstraint(f"type in {FIELD_TYPES}", name="type"),)


class ProjectField(Base):
    """A field attached to a project: display order and visibility are per project, so the same
    shared field can be positioned/shown differently across projects that use it."""

    __tablename__ = "project_fields"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("field_defs.id"), primary_key=True)
    position: Mapped[str] = mapped_column(POSITION)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)


class FieldValue(Base):
    """A task's value for a field, typed by the field's ``type`` (see FieldDef)."""

    __tablename__ = "field_values"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("field_defs.id"), primary_key=True)
    value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # created by migration 0008; declared here so autogenerate stops proposing to drop it
    __table_args__ = (Index("ix_field_values_value_gin", "value", postgresql_using="gin"),)
