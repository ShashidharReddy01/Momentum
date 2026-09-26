"""S3.1.1: `llm_calls` — one row per gateway call (`docs/architecture/data-model.md`).

Never stores prompt or response bodies: only what the usage page and budgets need.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

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
