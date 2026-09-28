"""s4_4_2 recurrence parent

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-28 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("recurrence_parent_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_tasks_recurrence_parent_id_tasks"),
        "tasks",
        "tasks",
        ["recurrence_parent_id"],
        ["id"],
    )
    op.create_index("ix_tasks_recurrence_parent", "tasks", ["recurrence_parent_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_recurrence_parent", table_name="tasks")
    op.drop_constraint(op.f("fk_tasks_recurrence_parent_id_tasks"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "recurrence_parent_id")
