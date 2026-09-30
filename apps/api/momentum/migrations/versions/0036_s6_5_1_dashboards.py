"""s6_5_1 dashboards

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-30 18:00:00.000000

S6.5.1: ``dashboards`` (a project's Dashboard tab, one per project, or a workspace dashboard) and
``dashboard_widgets`` (a validated ``query_spec`` run as the viewer, plus presentation in
``viz``). Both carry ``workspace_id``. New tables only; nothing existing changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("scope in ('project', 'workspace')", name=op.f("ck_dashboards_scope")),
        sa.CheckConstraint(
            "(scope = 'project') = (project_id is not null)",
            name=op.f("ck_dashboards_scope_project"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_dashboards_owner_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_dashboards_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_dashboards_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboards")),
    )
    op.create_index("ix_dashboards_workspace", "dashboards", ["workspace_id"], unique=False)
    op.create_index(
        "uq_dashboards_project",
        "dashboards",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at is null"),
    )
    op.create_table(
        "dashboard_widgets",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("query_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("viz", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("position", sa.String(length=64, collation="C"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "kind in ('count', 'bar', 'line', 'donut', 'list')",
            name=op.f("ck_dashboard_widgets_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_dashboard_widgets_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["dashboards.id"],
            name=op.f("fk_dashboard_widgets_dashboard_id_dashboards"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_dashboard_widgets_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboard_widgets")),
    )
    op.create_index(
        "ix_dashboard_widgets_dashboard",
        "dashboard_widgets",
        ["dashboard_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_widgets_dashboard", table_name="dashboard_widgets")
    op.drop_table("dashboard_widgets")
    op.drop_index("uq_dashboards_project", table_name="dashboards")
    op.drop_index("ix_dashboards_workspace", table_name="dashboards")
    op.drop_table("dashboards")
