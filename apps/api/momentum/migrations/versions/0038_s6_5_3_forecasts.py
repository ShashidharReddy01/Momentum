"""s6_5_3 forecasts

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-01 12:00:00.000000

S6.5.3: ``forecasts``: one row per project forecast (Monte Carlo P50/P80/P95 finish dates, a
0-100 risk score with its drivers, and the inputs it used). Carries ``workspace_id``. New table
only; nothing existing changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecasts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("p50", sa.Date(), nullable=True),
        sa.Column("p80", sa.Date(), nullable=True),
        sa.Column("p95", sa.Date(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("drivers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status in ('ok', 'done', 'no_history')", name=op.f("ck_forecasts_status")
        ),
        sa.CheckConstraint(
            "risk_level in ('none', 'low', 'medium', 'high')",
            name=op.f("ck_forecasts_risk_level"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_forecasts_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_forecasts_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecasts")),
    )
    op.create_index(
        "ix_forecasts_project_computed", "forecasts", ["project_id", "computed_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_forecasts_project_computed", table_name="forecasts")
    op.drop_table("forecasts")
