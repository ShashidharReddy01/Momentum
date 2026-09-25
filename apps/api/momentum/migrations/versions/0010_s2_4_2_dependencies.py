"""s2_4_2 dependencies

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-25 12:12:13.108398
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_dependencies",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("task_id <> depends_on_id", name=op.f("ck_task_dependencies_not_self")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_task_dependencies_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_id"], ["tasks.id"], name=op.f("fk_task_dependencies_depends_on_id_tasks")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_task_dependencies_task_id_tasks")
        ),
        sa.PrimaryKeyConstraint("task_id", "depends_on_id", name=op.f("pk_task_dependencies")),
    )


def downgrade() -> None:
    op.drop_table("task_dependencies")
