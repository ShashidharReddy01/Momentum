"""s2_7_1 import bookkeeping

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-25 13:43:57.773755
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_links",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_external_links_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_links")),
        sa.UniqueConstraint("provider", "entity_type", "external_id", name="uq_provider_gid"),
    )
    op.create_index(
        "ix_external_links_entity", "external_links", ["entity_type", "entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_external_links_workspace_id"), "external_links", ["workspace_id"], unique=False
    )
    op.create_table(
        "import_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("log", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("source in ('asana','csv')", name=op.f("ck_import_jobs_source")),
        sa.CheckConstraint(
            "status in ('pending', 'running', 'done', 'failed')", name=op.f("ck_import_jobs_status")
        ),
        sa.ForeignKeyConstraint(
            ["started_by"], ["users.id"], name=op.f("fk_import_jobs_started_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_import_jobs_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_jobs")),
    )
    op.create_index(
        op.f("ix_import_jobs_workspace_id"), "import_jobs", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_import_jobs_workspace_id"), table_name="import_jobs")
    op.drop_table("import_jobs")
    op.drop_index(op.f("ix_external_links_workspace_id"), table_name="external_links")
    op.drop_index("ix_external_links_entity", table_name="external_links")
    op.drop_table("external_links")
