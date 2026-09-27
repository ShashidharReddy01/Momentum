"""s4_1_5 rule ai steps

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-27 15:52:19.762553
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rule_ai_steps",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_run_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("field_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activity_batch_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'done', 'failed')",
            name=op.f("ck_rule_ai_steps_status"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_rule_ai_steps_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["rules.id"], name=op.f("fk_rule_ai_steps_rule_id_rules")
        ),
        sa.ForeignKeyConstraint(
            ["rule_run_id"], ["rule_runs.id"], name=op.f("fk_rule_ai_steps_rule_run_id_rule_runs")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_rule_ai_steps_task_id_tasks")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_rule_ai_steps_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_ai_steps")),
    )
    op.create_index("ix_rule_ai_steps_run", "rule_ai_steps", ["rule_run_id"], unique=False)
    op.create_index(
        "ix_rule_ai_steps_status", "rule_ai_steps", ["status", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_rule_ai_steps_status", table_name="rule_ai_steps")
    op.drop_index("ix_rule_ai_steps_run", table_name="rule_ai_steps")
    op.drop_table("rule_ai_steps")
