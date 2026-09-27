"""S4.3.1/S4.3.2: templates — a snapshot of a project's (or a task's) structure, replayed to
create a new one. See data-model.md."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

KINDS = ("project", "task")


class Template(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "templates"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    # Null for a project template (workspace-wide, reusable from any project); set for a task
    # template (S4.3.2: "per-project task templates").
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint(f"kind in {KINDS}", name="kind"),
        Index("ix_templates_workspace_kind", "workspace_id", "kind"),
    )
