"""S6.4.1: per-week capacity overrides (time off, a short week). See data-model.md §8."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base


class Capacity(Base):
    """One person's capacity for one week (``week_start`` is a Monday), overriding their standing
    weekly hours (``users.prefs['weekly_hours']``) and the workspace default."""

    __tablename__ = "capacity"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    capacity_minutes: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("capacity_minutes between 0 and 6000", name="minutes"),
        CheckConstraint("extract(isodow from week_start) = 1", name="monday"),
        Index("ix_capacity_workspace_week", "workspace_id", "week_start"),
    )
