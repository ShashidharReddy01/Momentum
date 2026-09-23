"""S0.1.5: core identity, activity, outbox, idempotency + job queue schema

Also installs required extensions (must be allow-listed on Azure PG Flexible) and the
Procrastinate job-queue schema inside the Momentum schema (ADR-0002).

Revision ID: 0001
Revises:
Create Date: 2026-09-23 05:12:31.310784
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from procrastinate.schema import SchemaManager
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EXTENSIONS = ("citext", "pg_trgm", "vector")


def _raw(sql: str) -> None:
    """Execute SQL on the raw psycopg connection (no bind-parameter parsing of '%' or ':')."""
    op.get_bind().connection.driver_connection.execute(sql)  # type: ignore[union-attr]


def upgrade() -> None:
    for ext in EXTENSIONS:
        _raw(f'CREATE EXTENSION IF NOT EXISTS "{ext}" SCHEMA public')
    # Procrastinate objects are created in the current search_path (the Momentum schema).
    _raw(SchemaManager.get_schema())

    op.create_table(
        "activity",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("verb", sa.String(length=80), nullable=False),
        sa.Column("diff", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("undo_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("ai_action_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity")),
    )
    op.create_index(op.f("ix_activity_batch_id"), "activity", ["batch_id"], unique=False)
    op.create_index(
        "ix_activity_entity", "activity", ["entity_type", "entity_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_activity_workspace_created", "activity", ["workspace_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_activity_workspace_id"), "activity", ["workspace_id"], unique=False)
    op.create_table(
        "events_outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events_outbox")),
    )
    op.create_index(
        "ix_events_outbox_undispatched",
        "events_outbox",
        ["id"],
        unique=False,
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name=op.f("pk_idempotency_keys")),
    )
    op.create_table(
        "workspaces",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("task_seq", sa.BigInteger(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("slug", name=op.f("uq_workspaces_slug")),
    )
    op.create_table(
        "users",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("is_agent", sa.Boolean(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("prefs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("role in ('admin','member','guest')", name=op.f("ck_users_role")),
        sa.CheckConstraint(
            "status in ('active','invited','disabled')", name=op.f("ck_users_status")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_users_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("workspace_id", "email", name=op.f("uq_users_workspace_id_email")),
    )
    op.create_index(op.f("ix_users_workspace_id"), "users", ["workspace_id"], unique=False)
    op.create_table(
        "api_tokens",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_api_tokens_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_api_tokens_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    op.create_index(op.f("ix_api_tokens_user_id"), "api_tokens", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_api_tokens_workspace_id"), "api_tokens", ["workspace_id"], unique=False
    )
    op.create_table(
        "user_identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email_at_link", postgresql.CITEXT(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_identities_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_identities")),
        sa.UniqueConstraint(
            "provider",
            "tenant_id",
            "subject",
            name=op.f("uq_user_identities_provider_tenant_id_subject"),
        ),
    )
    op.create_index(
        op.f("ix_user_identities_user_id"), "user_identities", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_identities_user_id"), table_name="user_identities")
    op.drop_table("user_identities")
    op.drop_index(op.f("ix_api_tokens_workspace_id"), table_name="api_tokens")
    op.drop_index(op.f("ix_api_tokens_user_id"), table_name="api_tokens")
    op.drop_table("api_tokens")
    op.drop_index(op.f("ix_users_workspace_id"), table_name="users")
    op.drop_table("users")
    op.drop_table("workspaces")
    op.drop_table("idempotency_keys")
    op.drop_index(
        "ix_events_outbox_undispatched",
        table_name="events_outbox",
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    op.drop_table("events_outbox")
    op.drop_index(op.f("ix_activity_workspace_id"), table_name="activity")
    op.drop_index("ix_activity_workspace_created", table_name="activity")
    op.drop_index("ix_activity_entity", table_name="activity")
    op.drop_index(op.f("ix_activity_batch_id"), table_name="activity")
    op.drop_table("activity")
    # Drop the Procrastinate objects (tables, then functions and types) from this schema.
    _raw(
        """
        DO $$
        DECLARE r record;
        BEGIN
          FOR r IN SELECT tablename FROM pg_tables
                   WHERE schemaname = current_schema() AND tablename LIKE 'procrastinate%' LOOP
            EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', r.tablename);
          END LOOP;
          FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p
                   JOIN pg_namespace n ON n.oid = p.pronamespace
                   WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate%' LOOP
            EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', r.sig);
          END LOOP;
          FOR r IN SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE n.nspname = current_schema() AND t.typname LIKE 'procrastinate%'
                     AND t.typtype IN ('e', 'c') LOOP
            EXECUTE format('DROP TYPE IF EXISTS %I CASCADE', r.typname);
          END LOOP;
        END $$;
        """
    )
