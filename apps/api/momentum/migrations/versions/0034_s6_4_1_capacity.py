"""s6_4_1 capacity

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-30 15:00:00.000000

S6.4.1: ``capacity``, one person's capacity for one week (a Monday), overriding their standing
weekly hours for time off or a short week. Carries ``workspace_id``. New table only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capacity",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("capacity_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("capacity_minutes between 0 and 6000", name=op.f("ck_capacity_minutes")),
        sa.CheckConstraint("extract(isodow from week_start) = 1", name=op.f("ck_capacity_monday")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_capacity_user_id_users")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_capacity_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("user_id", "week_start", name=op.f("pk_capacity")),
    )
    op.create_index("ix_capacity_workspace_week", "capacity", ["workspace_id", "week_start"])


def downgrade() -> None:
    op.drop_index("ix_capacity_workspace_week", table_name="capacity")
    op.drop_table("capacity")
