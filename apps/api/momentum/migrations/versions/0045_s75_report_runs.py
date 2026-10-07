"""s75 report runs

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-06 23:53:22.808907

Phase 7.5 S75-09 (spec §6.3), decision D75-55: ``report_runs``, one row per report requested
(who, the spec, queued/running/done/failed, the generated attachment, the error). The file
itself is an attachment (``source='generated'``). A new table only; nothing is rewritten.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_runs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("replace_id", sa.Uuid(), nullable=True),
        sa.Column("created_via", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'done', 'failed')", name=op.f("ck_report_runs_status")
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"],
            ["attachments.id"],
            name=op.f("fk_report_runs_attachment_id_attachments"),
        ),
        sa.ForeignKeyConstraint(
            ["replace_id"],
            ["attachments.id"],
            name=op.f("fk_report_runs_replace_id_attachments"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], name=op.f("fk_report_runs_requested_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_report_runs_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_runs")),
    )
    op.create_index(
        "ix_report_runs_workspace_created",
        "report_runs",
        ["workspace_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_report_runs_workspace_created", table_name="report_runs")
    op.drop_table("report_runs")
