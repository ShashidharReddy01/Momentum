from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

POSITION = String(64, collation="C")

# S2.6.2: same weighted-tsvector pattern as `tasks.search_tsv` (name outweighs the brief).
SEARCH_EXPR = (
    "setweight(to_tsvector('simple', coalesce(name, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(brief_text, '')), 'B')"
)


class Project(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "projects"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    color: Mapped[str | None] = mapped_column(String(16))
    icon: Mapped[str | None] = mapped_column(String(40))
    privacy: Mapped[str] = mapped_column(String(16), default="team")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    default_view: Mapped[str] = mapped_column(String(16), default="list")
    brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    brief_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(16))
    start_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    search_tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(SEARCH_EXPR, persisted=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_via: Mapped[str] = mapped_column(String(16), default="ui")

    __table_args__ = (
        CheckConstraint("privacy in ('team','private')", name="privacy"),
        CheckConstraint(
            "default_view in ('list','board','calendar','timeline','overview','dashboard')",
            name="default_view",
        ),
        CheckConstraint(
            "status is null or status in ('on_track','at_risk','off_track','on_hold','complete')",
            name="status",
        ),
        Index("ix_projects_search", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_projects_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="editor")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("role in ('admin','editor','commenter','viewer')", name="role"),
    )


class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    position: Mapped[str] = mapped_column(POSITION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_favorites_user_position", "user_id", "position"),)
