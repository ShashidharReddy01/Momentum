"""S3.4.3: status updates on a project (portfolios and goals later); see data-model.md."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

STATUSES = ("on_track", "at_risk", "off_track", "on_hold", "complete")
SECTION_KEYS = ("completed", "slipped", "blockers", "next")


class StatusUpdate(IdMixin, Base):
    """``body`` is ``{summary, sections: {completed|slipped|blockers|next: [{text}]}}``;
    ``body_text`` the same as plain text (search, embeddings, notifications). Task keys like
    ``[T-12]`` inside the text are resolved for each reader when shown."""

    __tablename__ = "status_updates"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    entity_type: Mapped[str] = mapped_column(String(16), default="project")
    entity_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    body_text: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_actions.id"))
    created_via: Mapped[str] = mapped_column(String(16), default="ui")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("entity_type in ('project', 'portfolio', 'goal')", name="entity_type"),
        CheckConstraint(f"status in {STATUSES}", name="status"),
        Index("ix_status_updates_entity", "entity_type", "entity_id", "created_at"),
    )
