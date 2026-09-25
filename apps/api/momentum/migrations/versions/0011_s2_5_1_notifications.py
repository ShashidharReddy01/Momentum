"""s2_5_1 notifications

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-25 12:38:30.866585
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind in ('assigned', 'mentioned', 'commented', 'completed', 'due_soon', 'overdue', "
            "'approval_requested', 'approval_decided', 'agent_proposal', 'digest')",
            name=op.f("ck_notifications_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"], ["activity.id"], name=op.f("fk_notifications_activity_id_activity")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_notifications_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        "ix_notifications_user_inbox", "notifications", ["user_id", "archived_at", "created_at"]
    )
    op.create_index(op.f("ix_notifications_workspace_id"), "notifications", ["workspace_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_workspace_id"), table_name="notifications")
    op.drop_index("ix_notifications_user_inbox", table_name="notifications")
    op.drop_table("notifications")
