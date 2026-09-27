"""s4_2_1 forms

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forms",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("public_enabled", sa.Boolean(), nullable=False),
        sa.Column("public_token", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_forms_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_forms_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["section_id"], ["sections.id"], name=op.f("fk_forms_section_id_sections")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_forms_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forms")),
        sa.UniqueConstraint("public_token", name="uq_forms_public_token"),
    )
    op.create_index("ix_forms_project_id", "forms", ["project_id"], unique=False)

    op.create_table(
        "form_submissions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["form_id"], ["forms.id"], name=op.f("fk_form_submissions_form_id_forms")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name=op.f("fk_form_submissions_submitted_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_form_submissions_task_id_tasks")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_form_submissions_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_submissions")),
    )
    op.create_index(
        "ix_form_submissions_form_created",
        "form_submissions",
        ["form_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_form_submissions_form_ip_created",
        "form_submissions",
        ["form_id", "ip_hash", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_form_submissions_form_ip_created", table_name="form_submissions")
    op.drop_index("ix_form_submissions_form_created", table_name="form_submissions")
    op.drop_table("form_submissions")
    op.drop_index("ix_forms_project_id", table_name="forms")
    op.drop_table("forms")
