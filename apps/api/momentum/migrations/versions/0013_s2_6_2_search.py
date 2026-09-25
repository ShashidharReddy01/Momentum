"""s2_6_2 search

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-25 13:32:33.719408
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "comments",
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(body_text, ''))", persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_comments_search", "comments", ["search_tsv"], unique=False, postgresql_using="gin"
    )
    op.add_column(
        "projects",
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('simple', coalesce(name, '')), 'A') || "
                "setweight(to_tsvector('simple', coalesce(brief_text, '')), 'B')",
                persisted=True,
            ),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_projects_name_trgm",
        "projects",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_projects_search", "projects", ["search_tsv"], unique=False, postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_projects_search", table_name="projects", postgresql_using="gin")
    op.drop_index(
        "ix_projects_name_trgm",
        table_name="projects",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_column("projects", "search_tsv")
    op.drop_index("ix_comments_search", table_name="comments", postgresql_using="gin")
    op.drop_column("comments", "search_tsv")
