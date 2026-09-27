"""s4_2_2 forms conversational

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-28 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "forms",
        sa.Column("conversational", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("forms", "conversational", server_default=None)


def downgrade() -> None:
    op.drop_column("forms", "conversational")
