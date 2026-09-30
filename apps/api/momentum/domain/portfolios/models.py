"""S6.2.2: portfolios — a named, ordered set of projects someone watches together, with its own
status updates (``status_updates.entity_type = 'portfolio'``). See data-model.md §8."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin
from momentum.domain.projects.models import POSITION

STATUSES = ("on_track", "at_risk", "off_track", "on_hold", "complete")


class Portfolio(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "portfolios"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # latest posted portfolio status, denormalized like projects.status
    status: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        CheckConstraint(f"status is null or status in {STATUSES}", name="status"),
        Index("ix_portfolios_workspace", "workspace_id"),
    )


class PortfolioItem(Base):
    __tablename__ = "portfolio_items"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id"), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    position: Mapped[str] = mapped_column(POSITION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_portfolio_items_project", "project_id"),)
