"""S6.5.1: dashboards — a named page of widgets, either a project's Dashboard tab
(``scope='project'``, one per project) or a workspace dashboard (``scope='workspace'``). A widget
stores a validated ``query_spec`` (v1, ``schemas.QuerySpec``) that is **run as the viewer** each
time it is read, never a stored result. See data-model.md §8."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from momentum.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin
from momentum.domain.projects.models import POSITION

SCOPES = ("project", "workspace")
KINDS = ("count", "bar", "line", "donut", "list")


class Dashboard(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "dashboards"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(16))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        CheckConstraint(f"scope in {SCOPES}", name="scope"),
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

    __table_args__ = (
        CheckConstraint(f"kind in {KINDS}", name="kind"),
        Index("ix_dashboard_widgets_dashboard", "dashboard_id", "position"),
    )
