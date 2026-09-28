"""s5_1_2 agent enabled_at

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-28 20:00:00.000000

When an agent was last switched on: event, assignment and mention triggers only react to what
happened after that, so enabling an agent never replays the workspace's history.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE agents SET enabled_at = updated_at WHERE enabled")


def downgrade() -> None:
    op.drop_column("agents", "enabled_at")
