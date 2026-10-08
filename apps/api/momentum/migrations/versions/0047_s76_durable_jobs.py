"""s76 durable jobs

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-08 22:00:00

Phase 7.6 S76-02 (spec §4.1; ADR-0012): **durable jobs**. A pack's work is an ``agent_runs`` row
with ``mode='job'``, replayed from its recorded steps; every existing run keeps ``mode='oneshot'``
(the server default) and runs exactly as before.

``agent_runs`` gains the job columns (``mode``, ``parent_run_id``, ``plan_id``/``plan_step_key``
(no FK until the plans table exists), ``capability``, ``waiting_on``, ``resume_at``, ``progress``,
``pack_version``, ``active_seconds``, ``attempt``, ``request_id``), and ``status`` gains
``waiting``, ``paused`` and ``expired``. ``request_id`` is filled for existing rows by
``gen_random_uuid()``; it's the id every activity row a job writes carries (undo everything).

New table ``agent_run_steps``: one row per recorded step, unique per ``(run_id, key)``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = "('queued', 'running', 'succeeded', 'failed', 'cancelled', 'budget_exceeded')"
NEW_STATUSES = (
    "('queued', 'running', 'waiting', 'paused', 'succeeded', 'failed', 'cancelled',"
    " 'budget_exceeded', 'expired')"
)


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("mode", sa.String(length=8), server_default="oneshot", nullable=False),
    )
    op.add_column("agent_runs", sa.Column("parent_run_id", sa.Uuid(), nullable=True))
    op.add_column("agent_runs", sa.Column("plan_id", sa.Uuid(), nullable=True))
    op.add_column("agent_runs", sa.Column("plan_step_key", sa.String(length=60), nullable=True))
    op.add_column("agent_runs", sa.Column("capability", sa.String(length=60), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("waiting_on", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("agent_runs", sa.Column("resume_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("agent_runs", sa.Column("pack_version", sa.String(length=20), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("active_seconds", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "agent_runs", sa.Column("attempt", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "request_id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        op.f("fk_agent_runs_parent_run_id_agent_runs"),
        "agent_runs",
        "agent_runs",
        ["parent_run_id"],
        ["id"],
    )
    op.drop_constraint(op.f("ck_agent_runs_status"), "agent_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_agent_runs_status"), "agent_runs", f"status in {NEW_STATUSES}"
    )
    op.create_check_constraint(
        op.f("ck_agent_runs_mode"), "agent_runs", "mode in ('oneshot', 'job')"
    )
    op.create_index("ix_agent_runs_parent", "agent_runs", ["parent_run_id"])
    op.create_index(
        "ix_agent_runs_jobs_due",
        "agent_runs",
        ["status", "resume_at"],
        postgresql_where=sa.text("mode = 'job'"),
    )

    op.create_table(
        "agent_run_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_ref", sa.String(length=200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind in ('step', 'llm', 'tool', 'ask', 'spawn', 'gather', 'consult', 'effect',"
            " 'now', 'sleep', 'event')",
            name=op.f("ck_agent_run_steps_kind"),
        ),
        sa.CheckConstraint(
            "status in ('running', 'done', 'failed')", name=op.f("ck_agent_run_steps_status")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_run_steps_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_run_steps_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_run_steps")),
        sa.UniqueConstraint("run_id", "key", name=op.f("uq_agent_run_steps_run_id")),
    )
    op.create_index("ix_agent_run_steps_run_seq", "agent_run_steps", ["run_id", "seq"])


def downgrade() -> None:
    # Jobs can't exist under the old shape: refuse rather than drop their history.
    bind = op.get_bind()
    n = bind.execute(sa.text("select count(*) from agent_runs where mode = 'job'")).scalar_one()
    if n:
        raise RuntimeError(f"{n} agent job(s) exist; remove them before downgrading below 0047")
    op.drop_index("ix_agent_run_steps_run_seq", table_name="agent_run_steps")
    op.drop_table("agent_run_steps")
    op.drop_index("ix_agent_runs_jobs_due", table_name="agent_runs")
    op.drop_index("ix_agent_runs_parent", table_name="agent_runs")
    op.drop_constraint(op.f("ck_agent_runs_mode"), "agent_runs", type_="check")
    op.drop_constraint(op.f("ck_agent_runs_status"), "agent_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_agent_runs_status"), "agent_runs", f"status in {OLD_STATUSES}"
    )
    op.drop_constraint(
        op.f("fk_agent_runs_parent_run_id_agent_runs"), "agent_runs", type_="foreignkey"
    )
    for column in (
        "request_id",
        "attempt",
        "active_seconds",
        "pack_version",
        "progress",
        "resume_at",
        "waiting_on",
        "capability",
        "plan_step_key",
        "plan_id",
        "parent_run_id",
        "mode",
    ):
        op.drop_column("agent_runs", column)
