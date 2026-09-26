"""s3_1_4 embeddings ai_summaries

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-26 08:13:20.912517
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _Vector(sa.types.UserDefinedType):  # type: ignore[type-arg]
    """pgvector column (kept local: migrations must not import app code that may change)."""

    cache_ok = True

    def get_col_spec(self, **_: object) -> str:
        return "vector(1024)"


def upgrade() -> None:
    op.create_table(
        "ai_summaries",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind in ('thread', 'project_week', 'inbox', 'task')", name=op.f("ck_ai_summaries_kind")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_ai_summaries_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_summaries")),
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            "kind",
            "content_hash",
            name=op.f("uq_ai_summaries_entity_type_entity_id_kind_content_hash"),
        ),
    )
    op.create_table(
        "embeddings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_no", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("embedding", _Vector(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "entity_type in ('task', 'comment', 'attachment', 'project', 'status_update')",
            name=op.f("ck_embeddings_entity_type"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_embeddings_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embeddings")),
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            "chunk_no",
            "model",
            name=op.f("uq_embeddings_entity_type_entity_id_chunk_no_model"),
        ),
    )
    op.create_index(
        "ix_embeddings_entity", "embeddings", ["entity_type", "entity_id"], unique=False
    )
    op.create_index(
        "ix_embeddings_hnsw",
        "embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_embeddings_workspace", "embeddings", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_embeddings_workspace", table_name="embeddings")
    op.drop_index(
        "ix_embeddings_hnsw",
        table_name="embeddings",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_embeddings_entity", table_name="embeddings")
    op.drop_table("embeddings")
    op.drop_table("ai_summaries")
