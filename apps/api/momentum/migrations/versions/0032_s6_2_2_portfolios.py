"""s6_2_2 portfolios

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-30 10:05:00.000000

S6.2.2: ``portfolios`` (a named set of projects with its own status, visible to every workspace
member, edited by its owner or an admin) and ``portfolio_items`` (which projects, in what order).
Both carry ``workspace_id``. New tables only; nothing existing changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "status is null or status in ('on_track', 'at_risk', 'off_track', 'on_hold', 'complete')",
            name=op.f("ck_portfolios_status"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_portfolios_owner_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_portfolios_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolios")),
    )
    op.create_index("ix_portfolios_workspace", "portfolios", ["workspace_id"], unique=False)
    op.create_table(
        "portfolio_items",
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.String(length=64, collation="C"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_portfolio_items_portfolio_id_portfolios"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_portfolio_items_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_portfolio_items_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("portfolio_id", "project_id", name=op.f("pk_portfolio_items")),
    )
    op.create_index("ix_portfolio_items_project", "portfolio_items", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_portfolio_items_project", table_name="portfolio_items")
    op.drop_table("portfolio_items")
    op.drop_index("ix_portfolios_workspace", table_name="portfolios")
    op.drop_table("portfolios")
