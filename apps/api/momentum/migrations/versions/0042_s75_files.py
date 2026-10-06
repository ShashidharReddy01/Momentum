"""s75 files: project files, versions, parse cache, conversation files

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-06 13:00:00.000000

Phase 7.5 (spec §3.1, §4.3, §4.8):

- ``attachments`` gains ``project_id`` and ``portfolio_id`` (new owners), ``source``,
  ``version_group``/``version``/``is_current`` (versions) and ``generated_spec`` (reports). The
  owner check becomes "exactly one of task, comment, project, portfolio". Backfill: every existing
  row is version 1 of its own group, current, ``source='upload'`` (``'agent'`` when an agent
  uploaded it). A row that named both a task and a comment keeps the comment (its task is the
  comment's task), so no link is lost.
- ``ai_conversation_files``: files attached to an Ask Mo chat only (private to its owner, deleted
  with the conversation).
- ``file_parses``: the parse cache (one row per file and parser version).
- ``projects.default_view`` may be ``files`` (the new Files tab).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.add_column("attachments", sa.Column("portfolio_id", sa.Uuid(), nullable=True))
    op.add_column(
        "attachments",
        sa.Column("source", sa.String(length=16), server_default="upload", nullable=False),
    )
    op.add_column("attachments", sa.Column("version_group", sa.Uuid(), nullable=True))
    op.add_column(
        "attachments", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column(
        "attachments",
        sa.Column("is_current", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "attachments",
        sa.Column("generated_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute("update attachments set version_group = id")
    op.execute(
        "update attachments a set source = 'agent' from users u "
        "where u.id = a.uploaded_by and u.is_agent"
    )
    op.execute(
        "update attachments set task_id = null where task_id is not null and comment_id is not null"
    )
    op.alter_column("attachments", "version_group", nullable=False)
    op.create_foreign_key(
        op.f("fk_attachments_project_id_projects"),
        "attachments",
        "projects",
        ["project_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_attachments_portfolio_id_portfolios"),
        "attachments",
        "portfolios",
        ["portfolio_id"],
        ["id"],
    )
    op.drop_constraint(op.f("ck_attachments_has_owner"), "attachments", type_="check")
    op.create_check_constraint(
        op.f("ck_attachments_one_owner"),
        "attachments",
        "num_nonnulls(task_id, comment_id, project_id, portfolio_id) = 1",
    )
    op.create_check_constraint(
        op.f("ck_attachments_source"),
        "attachments",
        "source in ('upload', 'generated', 'agent', 'import')",
    )
    op.create_index(
        "ix_attachments_project",
        "attachments",
        ["project_id"],
        postgresql_where=sa.text("deleted_at is null"),
    )
    op.create_index(
        "ix_attachments_portfolio",
        "attachments",
        ["portfolio_id"],
        postgresql_where=sa.text("deleted_at is null"),
    )
    op.create_index("ix_attachments_version_group", "attachments", ["version_group", "version"])
    # the project Files tab can be a project's default view
    op.drop_constraint(op.f("ck_projects_default_view"), "projects", type_="check")
    op.create_check_constraint(
        op.f("ck_projects_default_view"),
        "projects",
        "default_view in ('list','board','calendar','timeline','overview','files','dashboard')",
    )

    op.create_table(
        "ai_conversation_files",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("mime", sa.String(length=150), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_conversations.id"],
            name=op.f("fk_ai_conversation_files_conversation_id_ai_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ai_conversation_files_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_ai_conversation_files_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_conversation_files")),
    )
    op.create_index(
        "ix_ai_conversation_files_conversation", "ai_conversation_files", ["conversation_id"]
    )

    op.create_table(
        "file_parses",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_file_id", sa.Uuid(), nullable=True),
        sa.Column("parser_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rows_key", sa.String(length=300), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "parsed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status in ('ok', 'failed', 'unsupported', 'encrypted')",
            name=op.f("ck_file_parses_status"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(attachment_id, conversation_file_id) = 1",
            name=op.f("ck_file_parses_one_file"),
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"],
            ["attachments.id"],
            name=op.f("fk_file_parses_attachment_id_attachments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_file_id"],
            ["ai_conversation_files.id"],
            name=op.f("fk_file_parses_conversation_file_id_ai_conversation_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_file_parses_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_parses")),
    )
    op.create_index(
        "ix_file_parses_attachment",
        "file_parses",
        ["attachment_id", "parser_version"],
        unique=True,
    )
    op.create_index(
        "ix_file_parses_conversation_file",
        "file_parses",
        ["conversation_file_id", "parser_version"],
        unique=True,
    )


def downgrade() -> None:
    op.execute("update projects set default_view = 'list' where default_view = 'files'")
    op.drop_constraint(op.f("ck_projects_default_view"), "projects", type_="check")
    op.create_check_constraint(
        op.f("ck_projects_default_view"),
        "projects",
        "default_view in ('list','board','calendar','timeline','overview','dashboard')",
    )
    op.drop_index("ix_file_parses_conversation_file", table_name="file_parses")
    op.drop_index("ix_file_parses_attachment", table_name="file_parses")
    op.drop_table("file_parses")
    op.drop_index("ix_ai_conversation_files_conversation", table_name="ai_conversation_files")
    op.drop_table("ai_conversation_files")
    # project and portfolio files have no task or comment to fall back on: downgrading removes
    # those rows (their stored bytes stay in the storage backend)
    op.execute("delete from attachments where project_id is not null or portfolio_id is not null")
    op.drop_index("ix_attachments_version_group", table_name="attachments")
    op.drop_index("ix_attachments_portfolio", table_name="attachments")
    op.drop_index("ix_attachments_project", table_name="attachments")
    op.drop_constraint(op.f("ck_attachments_source"), "attachments", type_="check")
    op.drop_constraint(op.f("ck_attachments_one_owner"), "attachments", type_="check")
    op.create_check_constraint(
        op.f("ck_attachments_has_owner"),
        "attachments",
        "task_id is not null or comment_id is not null",
    )
    op.drop_constraint(
        op.f("fk_attachments_portfolio_id_portfolios"), "attachments", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_attachments_project_id_projects"), "attachments", type_="foreignkey"
    )
    for col in (
        "generated_spec",
        "is_current",
        "version",
        "version_group",
        "source",
        "portfolio_id",
        "project_id",
    ):
        op.drop_column("attachments", col)
