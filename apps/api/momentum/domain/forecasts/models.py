"""S6.5.3: project forecasts. One row per computation (nightly, or "refresh" from the overview);
the newest row per project is the current forecast. Computed data, never edited: rows record no
activity or undo (like embeddings), and a new one emits ``project.forecast_updated``."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin

STATUSES = ("ok", "done", "no_history")
LEVELS = ("none", "low", "medium", "high")


class Forecast(IdMixin, Base):
    __tablename__ = "forecasts"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    as_of: Mapped[date] = mapped_column(Date)
    # ok: dates below; done: nothing open; no_history: too little finished work to go on
    status: Mapped[str] = mapped_column(String(16))
    p50: Mapped[date | None] = mapped_column(Date)
    p80: Mapped[date | None] = mapped_column(Date)
    p95: Mapped[date | None] = mapped_column(Date)
    risk_score: Mapped[float] = mapped_column(Float)  # 0-100
    risk_level: Mapped[str] = mapped_column(String(8))
    # [{kind, text, points, tasks}] strongest first
    drivers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # {mode: tasks|hours, remaining, weeks, throughput: [...], chain_days, runs}
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(f"status in {STATUSES}", name="status"),
        CheckConstraint(f"risk_level in {LEVELS}", name="risk_level"),
        Index("ix_forecasts_project_computed", "project_id", "computed_at"),
    )
