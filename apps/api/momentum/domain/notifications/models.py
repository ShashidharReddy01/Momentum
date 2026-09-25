from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

# Kinds this slice (S2.5.1) actually generates. `approval_requested`/`approval_decided` (Phase 4
# workflow) and `agent_proposal`/`digest` (Phase 5 Pulse agent) are valid per data-model.md's own
# check constraint but nothing produces them yet — listed so a later phase's migration doesn't
# need to touch this constraint.
NOTIFICATION_KINDS = (
    "assigned",
    "mentioned",
    "commented",
    "completed",
    "due_soon",
    "overdue",
    "approval_requested",
    "approval_decided",
    "agent_proposal",
    "digest",
)


class Notification(IdMixin, Base):
    __tablename__ = "notifications"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID]
    activity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("activity.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"kind in {NOTIFICATION_KINDS}", name="kind"),
        Index("ix_notifications_user_inbox", "user_id", "archived_at", "created_at"),
    )
