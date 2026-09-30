"""s6_5_2 widget prompt

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-01 09:00:00.000000

S6.5.2: ``dashboard_widgets.created_from_prompt``: the question a chart was asked with when Mo
drafted it (null for charts built by hand), so the card can show it came from AI. A nullable
column; nothing existing changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dashboard_widgets", sa.Column("created_from_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("dashboard_widgets", "created_from_prompt")
