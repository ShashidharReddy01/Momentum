"""s3_1_3 ai_actions

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-26 07:52:26.617457
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_actions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("proposed_for", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("operations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk", sa.String(length=8), nullable=False),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_batch_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("risk in ('low', 'medium', 'high')", name=op.f("ck_ai_actions_risk")),
        sa.CheckConstraint(
            "source in ('chat', 'command', 'inline', 'agent', 'rule')",
            name=op.f("ck_ai_actions_source"),
        ),
        sa.CheckConstraint(
            "state in ('proposed', 'approved', 'applied', 'rejected', 'expired', 'undone', 'failed')",
            name=op.f("ck_ai_actions_state"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_ai_actions_decided_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["proposed_for"], ["users.id"], name=op.f("fk_ai_actions_proposed_for_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_ai_actions_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_actions")),
    )
    op.create_index(
        "ix_ai_actions_expiring",
        "ai_actions",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("state = 'proposed'"),
    )
    op.create_index(
        "ix_ai_actions_proposed_for_state", "ai_actions", ["proposed_for", "state"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_ai_actions_proposed_for_state", table_name="ai_actions")
    op.drop_index(
        "ix_ai_actions_expiring",
        table_name="ai_actions",
        postgresql_where=sa.text("state = 'proposed'"),
    )
    op.drop_table("ai_actions")
