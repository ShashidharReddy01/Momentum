"""s5_1_1 agents

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-28 18:00:00.000000

`agents` and `agent_runs` (data-model.md §9), the FKs deferred until they existed
(`users.agent_id`, `llm_calls.agent_run_id`), and the `agent_alert` notification kind.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "assigned",
    "mentioned",
    "commented",
    "completed",
    "due_soon",
    "overdue",
    "rule",
    "approval_requested",
    "approval_decided",
    "agent_proposal",
    "digest",
)
NEW_KINDS = (*OLD_KINDS, "agent_alert")


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("avatar", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("handler", sa.String(length=120), nullable=True),
        sa.Column("tools", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("autonomy", sa.String(length=16), nullable=False),
        sa.Column("triggers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_alias", sa.String(length=16), nullable=False),
        sa.Column("budget_monthly_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("budget_monthly_tokens", sa.BigInteger(), nullable=False),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("installed_hash", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind in ('llm', 'handler')", name=op.f("ck_agents_kind")),
        sa.CheckConstraint(
            "(kind = 'handler') = (handler is not null)", name=op.f("ck_agents_handler")
        ),
        sa.CheckConstraint(
            "autonomy in ('suggest', 'confirm', 'auto')", name=op.f("ck_agents_autonomy")
        ),
        sa.CheckConstraint(
            "model_alias in ('fast', 'default', 'smart')", name=op.f("ck_agents_model_alias")
        ),
        sa.CheckConstraint(
            "source in ('starter', 'host', 'custom')", name=op.f("ck_agents_source")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_agents_workspace_id_workspaces")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_agents_user_id_users")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_agents_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.UniqueConstraint("workspace_id", "key", name=op.f("uq_agents_workspace_id")),
        sa.UniqueConstraint("user_id", name=op.f("uq_agents_user_id")),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'budget_exceeded')",
            name=op.f("ck_agent_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_agent_runs_workspace_id_workspaces")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_agent_runs_agent_id_agents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint("agent_id", "dedupe_key", name=op.f("uq_agent_runs_agent_id")),
    )
    op.create_index("ix_agent_runs_agent_created", "agent_runs", ["agent_id", "created_at"])
    op.create_index("ix_agent_runs_workspace_created", "agent_runs", ["workspace_id", "created_at"])
    op.create_foreign_key(op.f("fk_users_agent_id_agents"), "users", "agents", ["agent_id"], ["id"])
    op.create_foreign_key(
        op.f("fk_llm_calls_agent_run_id_agent_runs"),
        "llm_calls",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_kind"), "notifications", f"kind in {NEW_KINDS}"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_kind"), "notifications", f"kind in {OLD_KINDS}"
    )
    op.drop_constraint(
        op.f("fk_llm_calls_agent_run_id_agent_runs"), "llm_calls", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_users_agent_id_agents"), "users", type_="foreignkey")
    op.drop_index("ix_agent_runs_workspace_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_created", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_table("agents")
