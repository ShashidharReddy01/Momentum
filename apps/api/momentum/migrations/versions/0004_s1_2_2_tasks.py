"""S1.2.2: tasks, task placements (task_projects), followers

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-23 10:26:48.153633
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("approval_state", sa.String(length=24), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("start_on", sa.Date(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("parent_position", sa.String(length=64, collation="C"), nullable=True),
        sa.Column("recurrence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("estimate_minutes", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=True),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || setweight(to_tsvector('simple', coalesce(description_text, '')), 'B')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_via", sa.String(length=16), nullable=False),
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
            "approval_state is null or approval_state in ('pending','approved','changes_requested','rejected')",
            name=op.f("ck_tasks_approval_state"),
        ),
        sa.CheckConstraint(
            "priority is null or priority in ('urgent','high','medium','low')",
            name=op.f("ck_tasks_priority"),
        ),
        sa.CheckConstraint("type in ('task','milestone','approval')", name=op.f("ck_tasks_type")),
        sa.CheckConstraint(
            "start_on is null or due_on is null or start_on <= due_on", name=op.f("ck_tasks_dates")
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], name=op.f("fk_tasks_assignee_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["completed_by"], ["users.id"], name=op.f("fk_tasks_completed_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_tasks_created_by_users")
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["tasks.id"], name=op.f("fk_tasks_parent_id_tasks")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_tasks_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        sa.UniqueConstraint("workspace_id", "number", name=op.f("uq_tasks_workspace_id_number")),
    )
    op.create_index(
        "ix_tasks_assignee_open", "tasks", ["assignee_id", "completed_at", "due_on"], unique=False
    )
    op.create_index("ix_tasks_parent", "tasks", ["parent_id", "parent_position"], unique=False)
    op.create_index(
        "ix_tasks_search", "tasks", ["search_tsv"], unique=False, postgresql_using="gin"
    )
    op.create_index(
        "ix_tasks_title_trgm",
        "tasks",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_table(
        "followers",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_followers_task_id_tasks")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_followers_user_id_users")),
        sa.PrimaryKeyConstraint("task_id", "user_id", name=op.f("pk_followers")),
    )
    op.create_index(op.f("ix_followers_user_id"), "followers", ["user_id"], unique=False)
    op.create_table(
        "task_projects",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.String(length=64, collation="C"), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["added_by"], ["users.id"], name=op.f("fk_task_projects_added_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_task_projects_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["section_id"], ["sections.id"], name=op.f("fk_task_projects_section_id_sections")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_task_projects_task_id_tasks")
        ),
        sa.PrimaryKeyConstraint("task_id", "project_id", name=op.f("pk_task_projects")),
    )
    op.create_index(
        "ix_task_projects_order",
        "task_projects",
        ["project_id", "section_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_task_projects_order", table_name="task_projects")
    op.drop_table("task_projects")
    op.drop_index(op.f("ix_followers_user_id"), table_name="followers")
    op.drop_table("followers")
    op.drop_index(
        "ix_tasks_title_trgm",
        table_name="tasks",
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.drop_index("ix_tasks_search", table_name="tasks", postgresql_using="gin")
    op.drop_index("ix_tasks_parent", table_name="tasks")
    op.drop_index("ix_tasks_assignee_open", table_name="tasks")
    op.drop_table("tasks")
