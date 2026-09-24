from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

_COLOR = String(7)


class Tag(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A workspace-level tag. Name is unique per workspace, case-insensitive (data-model.md
    §`tags`) — enforced by the functional unique index below, not a plain column constraint."""

    __tablename__ = "tags"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    color: Mapped[str] = mapped_column(_COLOR)

    __table_args__ = (
        Index(
            "ix_tags_workspace_name_ci",
            "workspace_id",
            func.lower(name),
            unique=True,
        ),
    )


class TaskTag(Base):
    """A tag applied to a task."""

    __tablename__ = "task_tags"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id"), primary_key=True)
