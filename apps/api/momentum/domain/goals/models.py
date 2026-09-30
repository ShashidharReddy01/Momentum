"""S6.3.1: goals (lite) — what a team is aiming for in a period, how it's measured, and which work
moves it. See data-model.md §8."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

SOURCES = ("manual", "projects", "subgoals")
STATUSES = ("on_track", "at_risk", "off_track", "on_hold", "complete")
LINK_TYPES = ("project", "portfolio")


class Goal(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "goals"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goals.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    period_label: Mapped[str | None] = mapped_column(String(40))  # e.g. "Q4 2026"
    # {type: number|percent|currency, start, target, current, unit?}; null = no metric
    metric: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    progress_source: Mapped[str] = mapped_column(String(16), default="manual")
    status: Mapped[str | None] = mapped_column(String(16))  # latest check-in
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        CheckConstraint(f"progress_source in {SOURCES}", name="progress_source"),
        CheckConstraint(f"status is null or status in {STATUSES}", name="status"),
        CheckConstraint("period_start <= period_end", name="period"),
        CheckConstraint("parent_id is null or parent_id <> id", name="not_own_parent"),
        Index("ix_goals_workspace_period", "workspace_id", "period_start", "period_end"),
        Index("ix_goals_parent", "parent_id"),
    )


class GoalLink(Base):
    __tablename__ = "goal_links"

    goal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goals.id"), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"entity_type in {LINK_TYPES}", name="entity_type"),
        Index("ix_goal_links_entity", "entity_type", "entity_id"),
    )
