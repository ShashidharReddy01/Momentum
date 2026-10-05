"""llm_calls index for the per-person AI rate limit

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-05 12:00:00.000000

Phase 7 S7.1.1: ``MOMENTUM_AI_USER_CALLS_PER_HOUR`` counts a person's own model calls in the last
hour before each new one; this index keeps that count cheap. No data changes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_llm_calls_user_created", "llm_calls", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_user_created", table_name="llm_calls")
