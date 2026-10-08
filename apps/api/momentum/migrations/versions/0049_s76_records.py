"""s76 records

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-09 12:00:00

Phase 7.6 S76-04 (spec §6.1-§6.2; ADR-0012): **records**, the structured things packs produce:
``record_types`` (each pack type's key and version, JSON Schema snapshot, display spec and data
classification, registered at install), ``records`` (validated data with provenance, checks, a
decision, promoted amount/currency/date, identity key, entity ids and a search vector) and
``record_versions`` (every version, with the correction operations that made it).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "record_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pack_key", sa.String(length=60), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("schema", JSONB, nullable=False),
        sa.Column("display", JSONB, nullable=False),
        sa.Column("classification", sa.String(length=12), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "classification in ('public', 'internal', 'financial', 'personal')",
            name=op.f("ck_record_types_classification"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_record_types_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record_types")),
        sa.UniqueConstraint(
            "workspace_id", "key", "version", name=op.f("uq_record_types_workspace_id")
        ),
    )
    op.create_table(
        "records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("type_version", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("source_attachment_id", sa.Uuid(), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_locator", sa.String(length=120), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_via", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("provenance", JSONB, nullable=False),
        sa.Column("checks", JSONB, nullable=False),
        sa.Column("decision", JSONB, nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("identity_key", sa.String(length=300), nullable=True),
        sa.Column("entity_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(search_text, ''))", persisted=True),
            nullable=True,
        ),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('draft', 'needs_review', 'ready', 'approved', 'rejected', 'void',"
            " 'superseded')",
            name=op.f("ck_records_status"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_records_workspace_id_workspaces")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_records_project_id_projects")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_records_task_id_tasks")),
        sa.ForeignKeyConstraint(
            ["source_attachment_id"],
            ["attachments.id"],
            name=op.f("fk_records_source_attachment_id_attachments"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["agent_runs.id"], name=op.f("fk_records_run_id_agent_runs")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_records_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_records")),
    )
    op.create_index(
        "ix_records_project_type_status",
        "records",
        ["project_id", "type", "status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_records_identity", "records", ["workspace_id", "type", "identity_key"])
    op.create_index("ix_records_occurred", "records", ["workspace_id", "type", "occurred_on"])
    op.create_index("ix_records_entity_ids", "records", ["entity_ids"], postgresql_using="gin")
    op.create_index("ix_records_search", "records", ["search"], postgresql_using="gin")
    op.create_index("ix_records_task", "records", ["task_id"])
    op.create_table(
        "record_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("provenance", JSONB, nullable=False),
        sa.Column("checks", JSONB, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("via", sa.String(length=12), nullable=False),
        sa.Column("change", JSONB, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "via in ('agent', 'review', 'api', 'undo')", name=op.f("ck_record_versions_via")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_record_versions_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["records.id"],
            name=op.f("fk_record_versions_record_id_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"], ["users.id"], name=op.f("fk_record_versions_changed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record_versions")),
        sa.UniqueConstraint("record_id", "version", name=op.f("uq_record_versions_record_id")),
    )


def downgrade() -> None:
    bind = op.get_bind()
    n = bind.execute(sa.text("select count(*) from records")).scalar_one()
    if n:
        raise RuntimeError(f"{n} record(s) exist; export and remove them before downgrading")
    op.drop_table("record_versions")
    op.drop_index("ix_records_task", table_name="records")
    op.drop_index("ix_records_search", table_name="records")
    op.drop_index("ix_records_entity_ids", table_name="records")
    op.drop_index("ix_records_occurred", table_name="records")
    op.drop_index("ix_records_identity", table_name="records")
    op.drop_index("ix_records_project_type_status", table_name="records")
    op.drop_table("records")
    op.drop_table("record_types")
