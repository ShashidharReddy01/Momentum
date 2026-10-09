"""s76 entities, skills, pack settings

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-09 18:00:00

Phase 7.6 S76-05 (spec §7.1, §7.2, §8.3; ADR-0012): ``entities`` (vendors and later customers,
with a trigram index on name and aliases; bank details only as a workspace-keyed fingerprint and
last four digits), ``agent_skills`` (what an agent learned and may use: proposed → active →
retired, with provenance, tryout and metrics) and ``agent_pack_settings`` (a pack's settings per
workspace, overridden per project).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050"
down_revision: str | None = "0049"
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
        "entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pack_key", sa.String(length=60), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("match_text", sa.Text(), nullable=False),
        sa.Column("attributes", JSONB, nullable=False),
        sa.Column("profile", JSONB, nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("merged_into", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_via", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status in ('active', 'merged', 'archived')", name=op.f("ck_entities_status")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_entities_workspace_id_workspaces")
        ),
        sa.ForeignKeyConstraint(
            ["merged_into"], ["entities.id"], name=op.f("fk_entities_merged_into_entities")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_entities_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
        sa.UniqueConstraint("workspace_id", "type", "key", name=op.f("uq_entities_workspace_id")),
    )
    op.create_index(
        "ix_entities_match_text",
        "entities",
        ["match_text"],
        postgresql_using="gin",
        postgresql_ops={"match_text": "gin_trgm_ops"},
    )
    op.create_index("ix_entities_type", "entities", ["workspace_id", "type", "status"])

    op.create_table(
        "agent_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pack_key", sa.String(length=60), nullable=False),
        sa.Column("scope_type", sa.String(length=12), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("field", sa.String(length=200), nullable=True),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("starter_key", sa.String(length=120), nullable=True),
        sa.Column("provenance", JSONB, nullable=False),
        sa.Column("tryout", JSONB, nullable=True),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("proposed_by", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "scope_type in ('workspace', 'entity', 'project')",
            name=op.f("ck_agent_skills_scope_type"),
        ),
        sa.CheckConstraint(
            "kind in ('hint', 'rule', 'example', 'field_map')", name=op.f("ck_agent_skills_kind")
        ),
        sa.CheckConstraint(
            "status in ('proposed', 'active', 'rejected', 'retired')",
            name=op.f("ck_agent_skills_status"),
        ),
        sa.CheckConstraint(
            "source in ('learned', 'authored', 'starter')", name=op.f("ck_agent_skills_source")
        ),
        sa.CheckConstraint(
            "(scope_type = 'workspace') = (scope_id is null)", name=op.f("ck_agent_skills_scope")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_skills_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["agent_skills.id"],
            name=op.f("fk_agent_skills_supersedes_id_agent_skills"),
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by"], ["users.id"], name=op.f("fk_agent_skills_proposed_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_agent_skills_decided_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_skills")),
    )
    op.create_index(
        "ix_agent_skills_lookup",
        "agent_skills",
        ["workspace_id", "pack_key", "status", "scope_type"],
    )

    op.create_table(
        "agent_pack_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pack_key", sa.String(length=60), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("values", JSONB, nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_pack_settings_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_agent_pack_settings_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_agent_pack_settings_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_pack_settings")),
    )
    op.create_index(
        "uq_agent_pack_settings_workspace",
        "agent_pack_settings",
        ["workspace_id", "pack_key"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )
    op.create_index(
        "uq_agent_pack_settings_project",
        "agent_pack_settings",
        ["workspace_id", "pack_key", "project_id"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("entities", "agent_skills"):
        n = bind.execute(sa.text(f"select count(*) from {table}")).scalar_one()  # noqa: S608 - fixed names
        if n:
            raise RuntimeError(f"{n} row(s) in {table}; export and remove them first")
    op.drop_index("uq_agent_pack_settings_project", table_name="agent_pack_settings")
    op.drop_index("uq_agent_pack_settings_workspace", table_name="agent_pack_settings")
    op.drop_table("agent_pack_settings")
    op.drop_index("ix_agent_skills_lookup", table_name="agent_skills")
    op.drop_table("agent_skills")
    op.drop_index("ix_entities_type", table_name="entities")
    op.drop_index("ix_entities_match_text", table_name="entities")
    op.drop_table("entities")
