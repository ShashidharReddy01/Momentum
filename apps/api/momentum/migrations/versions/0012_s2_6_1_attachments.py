"""s2_6_1 attachments

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-25 13:13:07.506756
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("comment_id", sa.Uuid(), nullable=True),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("mime", sa.String(length=150), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("text_extract", sa.Text(), nullable=True),
        sa.Column("extract_status", sa.String(length=20), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "extract_status in ('pending', 'done', 'skipped', 'failed')",
            name=op.f("ck_attachments_extract_status"),
        ),
        sa.CheckConstraint(
            "task_id is not null or comment_id is not null", name=op.f("ck_attachments_has_owner")
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"], ["comments.id"], name=op.f("fk_attachments_comment_id_comments")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_attachments_task_id_tasks")
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_attachments_uploaded_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_attachments_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
    )
    op.create_index("ix_attachments_comment", "attachments", ["comment_id"], unique=False)
    op.create_index("ix_attachments_task", "attachments", ["task_id"], unique=False)
    op.create_index(
        op.f("ix_attachments_workspace_id"), "attachments", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_attachments_workspace_id"), table_name="attachments")
    op.drop_index("ix_attachments_task", table_name="attachments")
    op.drop_index("ix_attachments_comment", table_name="attachments")
    op.drop_table("attachments")
