from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

POSITION = String(64, collation="C")


class Section(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "sections"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[str] = mapped_column(POSITION)
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (Index("ix_sections_project_position", "project_id", "position"),)
