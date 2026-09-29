from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base

BUCKETS = ("recently_assigned", "today", "this_week", "later")


class MyTaskPlacement(Base):
    """Where a task sits in its assignee's My Tasks (personal; nobody else sees it)."""

    __tablename__ = "my_task_placements"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    bucket: Mapped[str] = mapped_column(String(24))
    position: Mapped[str] = mapped_column(String(64, collation="C"))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # S5.3.4 (migration 0030): Nudge leaves this task alone for this person until this date
    nudge_snoozed_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "bucket in ('recently_assigned','today','this_week','later')", name="bucket"
        ),
        Index("ix_my_task_placements_user_bucket", "user_id", "bucket", "position"),
    )
