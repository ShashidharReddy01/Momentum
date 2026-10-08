"""s76 asks

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-09 09:00:00

Phase 7.6 S76-03 (spec §5.1; ADR-0012): **asks**, an agent's questions to people, made from a
durable job and answered from the task thread, the inbox, Mo or the API. Notification kinds gain
``agent_ask``, ``agent_ask_reminder`` and ``skill_proposed`` (the last used from S76-05).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048"
down_revision: str | None = "0047"
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
    "agent_alert",
    "unblocked",
)
NEW_KINDS = (*OLD_KINDS, "agent_ask", "agent_ask_reminder", "skill_proposed")


def upgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_kind"), "notifications", f"kind in {NEW_KINDS}"
    )
    op.create_table(
        "asks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(length=120), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("comment_id", sa.Uuid(), nullable=True),
        sa.Column("to_user_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("route", sa.String(length=60), nullable=False),
        sa.Column("route_fallback", sa.String(length=60), nullable=True),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("form", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("default_on_expiry", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("answered_by", sa.Uuid(), nullable=True),
        sa.Column("answered_via", sa.String(length=12), nullable=True),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminders_sent", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind in ('choice', 'confirm', 'form', 'text', 'pick_entity', 'pick_record')",
            name=op.f("ck_asks_kind"),
        ),
        sa.CheckConstraint(
            "status in ('open', 'answered', 'expired', 'cancelled', 'superseded')",
            name=op.f("ck_asks_status"),
        ),
        sa.CheckConstraint(
            "answered_via in ('card', 'thread', 'inbox', 'mo', 'api', 'expiry')",
            name=op.f("ck_asks_answered_via"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_asks_workspace_id_workspaces")
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name=op.f("fk_asks_agent_id_agents")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["agent_runs.id"], name=op.f("fk_asks_run_id_agent_runs")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_asks_task_id_tasks")),
        sa.ForeignKeyConstraint(
            ["comment_id"], ["comments.id"], name=op.f("fk_asks_comment_id_comments")
        ),
        sa.ForeignKeyConstraint(
            ["answered_by"], ["users.id"], name=op.f("fk_asks_answered_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"], ["asks.id"], name=op.f("fk_asks_superseded_by_asks")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asks")),
    )
    op.create_index(
        "uq_asks_run_step_live",
        "asks",
        ["run_id", "step_key"],
        unique=True,
        postgresql_where=sa.text("status <> 'superseded'"),
    )
    op.create_index("ix_asks_task", "asks", ["task_id"])
    op.create_index("ix_asks_open_due", "asks", ["status", "expires_at"])
    op.create_index("ix_asks_to_user_ids", "asks", ["to_user_ids"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_asks_to_user_ids", table_name="asks")
    op.drop_index("ix_asks_open_due", table_name="asks")
    op.drop_index("ix_asks_task", table_name="asks")
    op.drop_index("uq_asks_run_step_live", table_name="asks")
    op.drop_table("asks")
    op.execute(
        "DELETE FROM notifications WHERE kind IN"
        " ('agent_ask', 'agent_ask_reminder', 'skill_proposed')"
    )
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_kind"), "notifications", f"kind in {OLD_KINDS}"
    )
