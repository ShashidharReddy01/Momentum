from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

# S2.6.2: `docs/architecture/data-model.md §11` names `comments.body_text` as the tsvector
# source for keyword search — same unweighted `to_tsvector` pattern, one field, no A/B split.
SEARCH_EXPR = "to_tsvector('simple', coalesce(body_text, ''))"


class Comment(IdMixin, Base):
    __tablename__ = "comments"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"))
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    body_text: Mapped[str] = mapped_column(Text, default="")
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_via: Mapped[str] = mapped_column(String(16), default="ui")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(SEARCH_EXPR, persisted=True))

    __table_args__ = (
        Index("ix_comments_task_created", "task_id", "created_at"),
        Index("ix_comments_search", "search_tsv", postgresql_using="gin"),
    )


class Mention(IdMixin, Base):
    """Who/what a comment or description mentions: drives notifications and backlinks."""

    __tablename__ = "mentions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    source_type: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[uuid.UUID]
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("source_type in ('comment','task_description')", name="source_type"),
        CheckConstraint("target_type in ('user','task','project')", name="target_type"),
        UniqueConstraint("source_type", "source_id", "target_type", "target_id"),
        Index("ix_mentions_target", "target_type", "target_id"),
    )


class Reaction(IdMixin, Base):
    __tablename__ = "reactions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    emoji: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("entity_type in ('task','comment')", name="entity_type"),
        UniqueConstraint("entity_type", "entity_id", "user_id", "emoji"),
        Index("ix_reactions_entity", "entity_type", "entity_id"),
    )
