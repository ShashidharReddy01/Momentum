"""s3_1_1 llm_calls

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-26 02:18:02.876847
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("feature", sa.String(length=60), nullable=False),
        sa.Column("alias", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status in ('ok', 'error', 'budget_exceeded')", name=op.f("ck_llm_calls_status")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_llm_calls_user_id_users")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_llm_calls_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index(
        "ix_llm_calls_workspace_created", "llm_calls", ["workspace_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_llm_calls_workspace_created", table_name="llm_calls")
    op.drop_table("llm_calls")
