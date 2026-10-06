"""tag names unique among live tags only

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-06 12:00:00.000000

Phase 7 E7.0 (H54): the case-insensitive unique index on tag names also covered deleted tags, so
deleting a tag and creating one with the same name failed. It now covers live tags only (a
deleted tag keeps its rows so undo can bring it back). No data changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_tags_workspace_name_ci", table_name="tags")
    op.create_index(
        "ix_tags_workspace_name_ci",
        "tags",
        ["workspace_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at is null"),
    )


def downgrade() -> None:
    # fails if a deleted tag shares a live tag's name: rename or purge one first
    op.drop_index("ix_tags_workspace_name_ci", table_name="tags")
    op.create_index(
        "ix_tags_workspace_name_ci",
        "tags",
        ["workspace_id", sa.literal_column("lower(name)")],
        unique=True,
    )
