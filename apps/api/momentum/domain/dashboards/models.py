"""S6.5.1: dashboards — a named page of widgets, either a project's Dashboard tab
(``scope='project'``, one per project) or a workspace dashboard (``scope='workspace'``). A widget
stores a validated ``query_spec`` (v1, ``schemas.QuerySpec``) that is **run as the viewer** each
time it is read, never a stored result. See data-model.md §8."""

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

SCOPES = ("project", "workspace")
KINDS = (
    "count",
    "bar",
    "line",
    "donut",
    "list",
    # Phase 7.5 (spec §7.2)
    "kpi",
    "stacked_bar",
    "table",
    "funnel",
    "stage_time",
    "aging",
    "timeline",
    "note",
)
MEMBER_ROLES = ("editor", "viewer")
VISIT_SCOPES = ("home", "project", "portfolio")


class Dashboard(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "dashboards"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(16))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Phase 7.5 (spec §7.3, §7.4): saved filters {portfolio_id, period, owner, fields[]}, and the
    # portfolio whose Dashboard tab this is (one per portfolio)
    filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portfolios.id"), nullable=True
    )
    template: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        CheckConstraint(f"scope in {SCOPES}", name="scope"),
        Index(
            "uq_dashboards_portfolio",
            "portfolio_id",
            unique=True,
            postgresql_where=text("deleted_at is null and portfolio_id is not null"),
        ),
        CheckConstraint("(scope = 'project') = (project_id is not null)", name="scope_project"),
        Index("ix_dashboards_workspace", "workspace_id"),
        # one live dashboard per project (its Dashboard tab)
        Index(
            "uq_dashboards_project",
            "project_id",
            unique=True,
            postgresql_where=text("deleted_at is null"),
        ),
    )


class DashboardWidget(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "dashboard_widgets"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id"))
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    query_spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # presentation only: {"size": "sm" | "md" | "lg"}
    viz: Mapped[dict[str, Any]] = mapped_column(JSONB)
    position: Mapped[str] = mapped_column(POSITION)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # S6.5.2: the question Mo drafted this chart from (null when built by hand)
    created_from_prompt: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"kind in {KINDS}", name="kind"),
        Index("ix_dashboard_widgets_dashboard", "dashboard_id", "position"),
    )


class DashboardMember(Base):
    """Phase 7.5 (spec §7.4): who besides the owner edits a workspace dashboard. Viewing stays
    open to the workspace; numbers are always computed per viewer."""

    __tablename__ = "dashboard_members"

    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    role: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"role in {MEMBER_ROLES}", name="role"),
        Index("ix_dashboard_members_user", "user_id"),
    )


class DashboardPin(Base):
    """Phase 7.5 (spec §7.4): a dashboard pinned to one person's Home, in their order."""

    __tablename__ = "dashboard_pins"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id"), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    position: Mapped[str] = mapped_column(POSITION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserVisit(IdMixin, Base):
    """Phase 7.5 (spec §9.1): when a person last looked at a scope (``home``, a ``project``, a
    ``portfolio``), so "Catch me up" can say what changed since. Created by migration 0044 with
    the dashboards tables, used from S75-11. One row per (user, scope); Home has no scope id."""

    __tablename__ = "user_visits"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"scope_type in {VISIT_SCOPES}", name="scope_type"),
        CheckConstraint("(scope_type = 'home') = (scope_id is null)", name="scope_id"),
        Index(
            "uq_user_visits_scope",
            "user_id",
            "scope_type",
            "scope_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )
