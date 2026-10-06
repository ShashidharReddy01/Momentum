"""s75 dashboards v2: filters, portfolio tab, members, pins, more widget kinds; user visits

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-06 22:30:00.000000

Phase 7.5 (spec §7.3, §7.4, §9.1), decision D75-5:

- ``dashboards`` gains ``filters`` (jsonb, ``{}``), ``portfolio_id`` (a portfolio's Dashboard
  tab; one live dashboard per portfolio) and ``template`` (the role template it was made from).
- ``dashboard_widgets.kind`` may also be ``kpi``, ``stacked_bar``, ``table``, ``funnel``,
  ``stage_time``, ``aging``, ``timeline`` and ``note``.
- ``dashboard_members`` (editor/viewer), ``dashboard_pins`` (a dashboard on a person's Home).
- ``user_visits`` (the last time a person looked at Home, a project or a portfolio; S75-11).

Nothing existing is dropped or rewritten.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
OLD_KINDS = "kind in ('count', 'bar', 'line', 'donut', 'list')"
NEW_KINDS = (
    "kind in ('count', 'bar', 'line', 'donut', 'list', 'kpi', 'stacked_bar', 'table', "
    "'funnel', 'stage_time', 'aging', 'timeline', 'note')"
)
POSITION = sa.String(length=64, collation="C")


def upgrade() -> None:
    op.add_column(
        "dashboards",
        sa.Column("filters", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column("dashboards", sa.Column("portfolio_id", sa.Uuid(), nullable=True))
    op.add_column("dashboards", sa.Column("template", sa.String(length=40), nullable=True))
    op.create_foreign_key(
        op.f("fk_dashboards_portfolio_id_portfolios"),
        "dashboards",
        "portfolios",
        ["portfolio_id"],
        ["id"],
    )
    op.create_index(
        "uq_dashboards_portfolio",
        "dashboards",
        ["portfolio_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at is null and portfolio_id is not null"),
    )
    op.drop_constraint(op.f("ck_dashboard_widgets_kind"), "dashboard_widgets", type_="check")
    op.create_check_constraint(op.f("ck_dashboard_widgets_kind"), "dashboard_widgets", NEW_KINDS)

    op.create_table(
        "dashboard_members",
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role in ('editor', 'viewer')", name=op.f("ck_dashboard_members_role")),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["dashboards.id"],
            name=op.f("fk_dashboard_members_dashboard_id_dashboards"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_dashboard_members_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_dashboard_members_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("dashboard_id", "user_id", name=op.f("pk_dashboard_members")),
    )
    op.create_index("ix_dashboard_members_user", "dashboard_members", ["user_id"])

    op.create_table(
        "dashboard_pins",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("position", POSITION, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["dashboards.id"],
            name=op.f("fk_dashboard_pins_dashboard_id_dashboards"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_dashboard_pins_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_dashboard_pins_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("user_id", "dashboard_id", name=op.f("pk_dashboard_pins")),
    )

    op.create_table(
        "user_visits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type in ('home', 'project', 'portfolio')",
            name=op.f("ck_user_visits_scope_type"),
        ),
        sa.CheckConstraint(
            "(scope_type = 'home') = (scope_id is null)", name=op.f("ck_user_visits_scope_id")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_visits_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_user_visits_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_visits")),
    )
    op.create_index(
        "uq_user_visits_scope",
        "user_visits",
        ["user_id", "scope_type", "scope_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index("uq_user_visits_scope", table_name="user_visits")
    op.drop_table("user_visits")
    op.drop_table("dashboard_pins")
    op.drop_index("ix_dashboard_members_user", table_name="dashboard_members")
    op.drop_table("dashboard_members")
    # widgets of the new kinds can't stay under the old constraint
    op.execute(
        "update dashboard_widgets set deleted_at = coalesce(deleted_at, now()), kind = 'count' "
        "where kind not in ('count', 'bar', 'line', 'donut', 'list')"
    )
    op.drop_constraint(op.f("ck_dashboard_widgets_kind"), "dashboard_widgets", type_="check")
    op.create_check_constraint(op.f("ck_dashboard_widgets_kind"), "dashboard_widgets", OLD_KINDS)
    op.drop_index("uq_dashboards_portfolio", table_name="dashboards")
    op.drop_constraint(
        op.f("fk_dashboards_portfolio_id_portfolios"), "dashboards", type_="foreignkey"
    )
    op.drop_column("dashboards", "template")
    op.drop_column("dashboards", "portfolio_id")
    op.drop_column("dashboards", "filters")
