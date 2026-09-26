"""s3_4_3 status updates

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-26 10:55:21.374953
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "status_updates",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("generated_by_ai", sa.Boolean(), nullable=False),
        sa.Column("ai_action_id", sa.Uuid(), nullable=True),
        sa.Column("created_via", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "entity_type in ('project', 'portfolio', 'goal')",
            name=op.f("ck_status_updates_entity_type"),
        ),
        sa.CheckConstraint(
            "status in ('on_track', 'at_risk', 'off_track', 'on_hold', 'complete')",
            name=op.f("ck_status_updates_status"),
        ),
        sa.ForeignKeyConstraint(
            ["ai_action_id"],
            ["ai_actions.id"],
            name=op.f("fk_status_updates_ai_action_id_ai_actions"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_status_updates_author_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_status_updates_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_status_updates")),
    )
    op.create_index(
        "ix_status_updates_entity",
        "status_updates",
        ["entity_type", "entity_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_status_updates_entity", table_name="status_updates")
    op.drop_table("status_updates")
