"""s3_1_5 ai_memory

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-26 08:27:51.806657
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_memory",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=12), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(scope = 'workspace') = (scope_id is null)",
            name=op.f("ck_ai_memory_scope_id_matches_scope"),
        ),
        sa.CheckConstraint(
            "scope in ('workspace', 'team', 'project')", name=op.f("ck_ai_memory_scope")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_ai_memory_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_ai_memory_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_memory")),
    )
    op.create_index(
        "ix_ai_memory_scope", "ai_memory", ["workspace_id", "scope", "scope_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_ai_memory_scope", table_name="ai_memory")
    op.drop_table("ai_memory")
