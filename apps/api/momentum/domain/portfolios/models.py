"""S6.2.2: portfolios — a named, ordered set of projects someone watches together, with its own
status updates (``status_updates.entity_type = 'portfolio'``). See data-model.md §8."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin
from momentum.domain.projects.models import POSITION

STATUSES = ("on_track", "at_risk", "off_track", "on_hold", "complete")
KINDS = ("manual", "rule")
LAYOUTS = ("table", "board", "timeline", "workload")
MEMBER_ROLES = ("editor", "viewer")


class Portfolio(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "portfolios"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # latest posted portfolio status, denormalized like projects.status
    status: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Phase 7.5 (spec §5.2): a rule portfolio computes its projects (as the viewer) from `rule`
    kind: Mapped[str] = mapped_column(String(8), default="manual", server_default="manual")
    rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # the single-select project field whose option order is the lifecycle, its SLA in days per
    # option ({option_id: days}) and its gates ({option_id: {required_fields, required_milestones,
    # required_files}})
    stage_field_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("field_defs.id"), nullable=True
    )
    stage_targets: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    stage_gates: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    columns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        CheckConstraint(f"status is null or status in {STATUSES}", name="status"),
        CheckConstraint(f"kind in {KINDS}", name="kind"),
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


class PortfolioView(IdMixin, Base):
    """Phase 7.5 (spec §5.2): a saved view of a portfolio; personal (owner set) or shared."""

    __tablename__ = "portfolio_views"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id"))
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    layout: Mapped[str] = mapped_column(String(10), default="table", server_default="table")
    filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    group_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sort: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"layout in {LAYOUTS}", name="layout"),
        Index("ix_portfolio_views_portfolio", "portfolio_id"),
    )


class PortfolioMember(Base):
    """Phase 7.5 (spec §5.6): who may edit (or, for guests, see) a portfolio besides its owner."""

    __tablename__ = "portfolio_members"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    role: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"role in {MEMBER_ROLES}", name="role"),
        Index("ix_portfolio_members_user", "user_id"),
    )
