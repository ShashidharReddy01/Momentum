"""s2_3_3 tags

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-24 09:43:21.779554
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_tags_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
    )
    op.create_index(op.f("ix_tags_workspace_id"), "tags", ["workspace_id"], unique=False)
    op.create_index(
        "ix_tags_workspace_name_ci",
        "tags",
        ["workspace_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "task_tags",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], name=op.f("fk_task_tags_tag_id_tags")),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_task_tags_task_id_tasks")),
        sa.PrimaryKeyConstraint("task_id", "tag_id", name=op.f("pk_task_tags")),
    )


def downgrade() -> None:
    op.drop_table("task_tags")
    op.drop_index("ix_tags_workspace_name_ci", table_name="tags")
    op.drop_index(op.f("ix_tags_workspace_id"), table_name="tags")
    op.drop_table("tags")
