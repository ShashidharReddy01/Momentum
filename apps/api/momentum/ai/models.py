"""S3.1.1: `llm_calls` — one row per gateway call (`docs/architecture/data-model.md`).

Never stores prompt or response bodies: only what the usage page and budgets need.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.ai.vector import Vector
from momentum.core.db import Base, IdMixin

LLM_CALL_STATUSES = ("ok", "error", "budget_exceeded")


class LlmCall(IdMixin, Base):
    __tablename__ = "llm_calls"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    feature: Mapped[str] = mapped_column(String(60))
    alias: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # agent_runs arrives in Phase 5; the FK is added then.
    agent_run_id: Mapped[uuid.UUID | None]
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latency_ms: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"status in {LLM_CALL_STATUSES}", name="status"),
        Index("ix_llm_calls_workspace_created", "workspace_id", "created_at"),
    )


AI_ACTION_SOURCES = ("chat", "command", "inline", "agent", "rule")
AI_ACTION_STATES = ("proposed", "approved", "applied", "rejected", "expired", "undone", "failed")
AI_ACTION_RISKS = ("low", "medium", "high")


class AiAction(IdMixin, Base):
    """S3.1.3: an AI-proposed change, previewed and waiting for (or done with) a human decision.

    ``operations`` is ``[{tool, args, summary, risk, diff, watch}]``: the tool call, what its dry
    run showed, and the version of every existing entity it touches (``watch``) for the stale
    check before applying. ai-architecture §4."""

    __tablename__ = "ai_actions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    source: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[uuid.UUID | None]
    proposed_for: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    summary: Mapped[str] = mapped_column(Text)
    operations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    risk: Mapped[str] = mapped_column(String(8))
    state: Mapped[str] = mapped_column(String(12), default="proposed")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_batch_id: Mapped[uuid.UUID | None]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"source in {AI_ACTION_SOURCES}", name="source"),
        CheckConstraint(f"state in {AI_ACTION_STATES}", name="state"),
        CheckConstraint(f"risk in {AI_ACTION_RISKS}", name="risk"),
        Index("ix_ai_actions_proposed_for_state", "proposed_for", "state"),
        Index(
            "ix_ai_actions_expiring",
            "expires_at",
            postgresql_where=text("state = 'proposed'"),
        ),
    )


EMBED_ENTITY_TYPES = ("task", "comment", "attachment", "project", "status_update")
EMBED_DIM = 1024  # must match MOMENTUM_LLM_EMBED_DIM; a different size needs a migration


class Embedding(IdMixin, Base):
    """S3.1.4: one chunk of an entity's text and its vector (``input_type=search_document``).

    ``content_hash`` covers model + chunk text, so re-indexing unchanged content costs nothing.
    Rows are derived data: safe to delete and rebuild with ``momentum reindex``."""

    __tablename__ = "embeddings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID]
    chunk_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200))
    dim: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"entity_type in {EMBED_ENTITY_TYPES}", name="entity_type"),
        UniqueConstraint("entity_type", "entity_id", "chunk_no", "model"),
        Index("ix_embeddings_entity", "entity_type", "entity_id"),
        Index("ix_embeddings_workspace", "workspace_id"),
        Index(
            "ix_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class AiSummary(IdMixin, Base):
    """S3.1.4: cached summaries keyed by content hash (a cache: safe to purge). Filled by the
    summary features (S3.4.1) and long-thread context building (S3.1.5)."""

    __tablename__ = "ai_summaries"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("kind in ('thread', 'project_week', 'inbox', 'task')", name="kind"),
        UniqueConstraint("entity_type", "entity_id", "kind", "content_hash"),
    )
