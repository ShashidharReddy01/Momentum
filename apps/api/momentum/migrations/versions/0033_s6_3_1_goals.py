"""s6_3_1 goals

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-30 11:00:00.000000

S6.3.1: ``goals`` (a period, an optional metric, where progress comes from, the latest check-in
status; sub-goals via ``parent_id``) and ``goal_links`` (the projects and portfolios that move a
goal). Both carry ``workspace_id``. New tables only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_label", sa.String(length=40), nullable=True),
        sa.Column("metric", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("progress_source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(
            "progress_source in ('manual', 'projects', 'subgoals')",
            name=op.f("ck_goals_progress_source"),
        ),
        sa.CheckConstraint(
            "status is null or status in ('on_track', 'at_risk', 'off_track', 'on_hold', 'complete')",
            name=op.f("ck_goals_status"),
        ),
        sa.CheckConstraint("period_start <= period_end", name=op.f("ck_goals_period")),
        sa.CheckConstraint(
            "parent_id is null or parent_id <> id", name=op.f("ck_goals_not_own_parent")
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_goals_owner_id_users")),
        sa.ForeignKeyConstraint(["parent_id"], ["goals.id"], name=op.f("fk_goals_parent_id_goals")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_goals_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goals")),
    )
    op.create_index(
        "ix_goals_workspace_period", "goals", ["workspace_id", "period_start", "period_end"]
    )
    op.create_index("ix_goals_parent", "goals", ["parent_id"])
    op.create_table(
        "goal_links",
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type in ('project', 'portfolio')", name=op.f("ck_goal_links_entity_type")
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"], ["goals.id"], name=op.f("fk_goal_links_goal_id_goals")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_goal_links_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("goal_id", "entity_type", "entity_id", name=op.f("pk_goal_links")),
    )
    op.create_index("ix_goal_links_entity", "goal_links", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_index("ix_goal_links_entity", table_name="goal_links")
    op.drop_table("goal_links")
    op.drop_index("ix_goals_parent", table_name="goals")
    op.drop_index("ix_goals_workspace_period", table_name="goals")
    op.drop_table("goals")
