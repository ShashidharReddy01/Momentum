from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

# Kinds this slice (S2.5.1) actually generates, plus `rule` (S4.1.2's `notify_user` action).
# `approval_requested`/`approval_decided` (Phase 4 workflow) and `agent_proposal`/`digest`
# (Phase 5 Pulse agent) are valid per data-model.md's own check constraint but nothing produces
# them yet — listed so a later phase's migration doesn't need to touch this constraint.
# `agent_alert` (migration 0028, S5.1.1): an agent needs an admin's attention (budget exceeded,
# repeated failure, auto-demotion); produced from S5.1.2.
NOTIFICATION_KINDS = (
    "assigned",
    "mentioned",
    "commented",
    "completed",
    "due_soon",
    "overdue",
    "rule",
    "approval_requested",
    "approval_decided",
    "agent_proposal",
    "digest",
    "agent_alert",
    "unblocked",  # S6.1.3: a task's last blocker is done ("You're up")
    # Phase 7.6 S76-03: an agent asks you something; a reminder of it; a skill to review (S76-05)
    "agent_ask",
    "agent_ask_reminder",
    "skill_proposed",
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
