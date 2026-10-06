"""s75 lifecycle: project fields and history, template lineage, portfolios v2, snapshots

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-06 18:00:00.000000

Phase 7.5 (spec §5.1, §5.2, §5.5, §5.7), one migration for the lifecycle model (decision D75-5):

- ``field_defs.applies_to`` (``task`` default, or ``project``).
- ``project_field_values`` (a project's value per project field) and ``project_field_events``
  (history: every change of a project field, written with the change).
- ``projects.template_id``: the template a project was made from (null for every existing
  project, Asana imports included).
- ``portfolios`` gain ``kind`` (``manual`` default for every existing portfolio), ``rule``,
  ``stage_field_id``, ``stage_targets``, ``stage_gates`` and ``columns``.
- ``portfolio_views`` (saved views, personal or shared), ``portfolio_members`` (editor/viewer)
  and ``project_snapshots`` (one row per project and day, for trends).

Nothing existing is dropped or rewritten; the new columns have defaults.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "field_defs",
        sa.Column("applies_to", sa.String(length=8), server_default="task", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_field_defs_applies_to"), "field_defs", "applies_to in ('task', 'project')"
    )
    op.add_column("projects", sa.Column("template_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_projects_template_id_templates"), "projects", "templates", ["template_id"], ["id"]
    )
    op.create_index(
        "ix_projects_template",
        "projects",
        ["template_id"],
        postgresql_where=sa.text("template_id is not null"),
    )

    op.create_table(
        "project_field_values",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("field_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_field_values_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["field_id"],
            ["field_defs.id"],
            name=op.f("fk_project_field_values_field_id_field_defs"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_project_field_values_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_project_field_values_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("project_id", "field_id", name=op.f("pk_project_field_values")),
    )
    op.create_index("ix_project_field_values_field", "project_field_values", ["field_id"])

    op.create_table(
        "project_field_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("field_id", sa.Uuid(), nullable=False),
        sa.Column("old", JSONB, nullable=True),
        sa.Column("new", JSONB, nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_field_events_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["field_id"],
            ["field_defs.id"],
            name=op.f("fk_project_field_events_field_id_field_defs"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_project_field_events_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_project_field_events_actor_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_field_events")),
    )
    op.create_index(
        "ix_project_field_events_project_field_at",
        "project_field_events",
        ["project_id", "field_id", "at"],
    )
    op.create_index("ix_project_field_events_field_at", "project_field_events", ["field_id", "at"])

    op.add_column(
        "portfolios",
        sa.Column("kind", sa.String(length=8), server_default="manual", nullable=False),
    )
    op.add_column("portfolios", sa.Column("rule", JSONB, nullable=True))
    op.add_column("portfolios", sa.Column("stage_field_id", sa.Uuid(), nullable=True))
    op.add_column(
        "portfolios",
        sa.Column("stage_targets", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "portfolios",
        sa.Column("stage_gates", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "portfolios",
        sa.Column("columns", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_portfolios_kind"), "portfolios", "kind in ('manual', 'rule')"
    )
    op.create_foreign_key(
        op.f("fk_portfolios_stage_field_id_field_defs"),
        "portfolios",
        "field_defs",
        ["stage_field_id"],
        ["id"],
    )

    op.create_table(
        "portfolio_views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("layout", sa.String(length=10), server_default="table", nullable=False),
        sa.Column("filters", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("group_by", sa.String(length=80), nullable=True),
        sa.Column("sort", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
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
            "layout in ('table', 'board', 'timeline', 'workload')",
            name=op.f("ck_portfolio_views_layout"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_portfolio_views_portfolio_id_portfolios"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_portfolio_views_owner_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_portfolio_views_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_views")),
    )
    op.create_index("ix_portfolio_views_portfolio", "portfolio_views", ["portfolio_id"])

    op.create_table(
        "portfolio_members",
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role in ('editor', 'viewer')", name=op.f("ck_portfolio_members_role")),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_portfolio_members_portfolio_id_portfolios"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_portfolio_members_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_portfolio_members_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("portfolio_id", "user_id", name=op.f("pk_portfolio_members")),
    )
    op.create_index("ix_portfolio_members_user", "portfolio_members", ["user_id"])

    op.create_table(
        "project_snapshots",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_project_snapshots_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_project_snapshots_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("project_id", "day", name=op.f("pk_project_snapshots")),
    )
    op.create_index(
        "ix_project_snapshots_workspace_day", "project_snapshots", ["workspace_id", "day"]
    )


def downgrade() -> None:
    op.drop_index("ix_project_snapshots_workspace_day", table_name="project_snapshots")
    op.drop_table("project_snapshots")
    op.drop_index("ix_portfolio_members_user", table_name="portfolio_members")
    op.drop_table("portfolio_members")
    op.drop_index("ix_portfolio_views_portfolio", table_name="portfolio_views")
    op.drop_table("portfolio_views")
    op.drop_constraint(
        op.f("fk_portfolios_stage_field_id_field_defs"), "portfolios", type_="foreignkey"
    )
    op.drop_constraint(op.f("ck_portfolios_kind"), "portfolios", type_="check")
    for col in ("columns", "stage_gates", "stage_targets", "stage_field_id", "rule", "kind"):
        op.drop_column("portfolios", col)
    op.drop_index("ix_project_field_events_field_at", table_name="project_field_events")
    op.drop_index("ix_project_field_events_project_field_at", table_name="project_field_events")
    op.drop_table("project_field_events")
    op.drop_index("ix_project_field_values_field", table_name="project_field_values")
    op.drop_table("project_field_values")
    op.drop_index("ix_projects_template", table_name="projects")
    op.drop_constraint(op.f("fk_projects_template_id_templates"), "projects", type_="foreignkey")
    op.drop_column("projects", "template_id")
    op.drop_constraint(op.f("ck_field_defs_applies_to"), "field_defs", type_="check")
    op.drop_column("field_defs", "applies_to")
