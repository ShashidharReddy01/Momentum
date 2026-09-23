from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

POSITION = String(64, collation="C")

SEARCH_EXPR = (
    "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(description_text, '')), 'B')"
)


class Task(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tasks"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    number: Mapped[int] = mapped_column()
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    description_text: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(16), default="task")
    approval_state: Mapped[str | None] = mapped_column(String(24))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    start_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"))
    parent_position: Mapped[str | None] = mapped_column(POSITION)
    recurrence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    estimate_minutes: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[str | None] = mapped_column(String(16))
    search_tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(SEARCH_EXPR, persisted=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_via: Mapped[str] = mapped_column(String(16), default="ui")

    __table_args__ = (
        UniqueConstraint("workspace_id", "number"),
        CheckConstraint("type in ('task','milestone','approval')", name="type"),
        CheckConstraint(
            "approval_state is null or approval_state in "
            "('pending','approved','changes_requested','rejected')",
            name="approval_state",
        ),
        CheckConstraint(
            "priority is null or priority in ('urgent','high','medium','low')", name="priority"
        ),
        CheckConstraint("start_on is null or due_on is null or start_on <= due_on", name="dates"),
        Index("ix_tasks_assignee_open", "assignee_id", "completed_at", "due_on"),
        Index("ix_tasks_parent", "parent_id", "parent_position"),
        Index("ix_tasks_search", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_tasks_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )


class TaskProject(Base):
    """Placement of a task in a project section (multi-homing ready)."""

    __tablename__ = "task_projects"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"))
    position: Mapped[str] = mapped_column(POSITION)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (Index("ix_task_projects_order", "project_id", "section_id", "position"),)


class Follower(Base):
    __tablename__ = "followers"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
