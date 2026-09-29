"""s5_3_4 nudge snooze

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-29 18:00:00.000000

S5.3.4 (kickoff Q7): a person can snooze Nudge's reminders on one of their tasks until a date.
Stored on their own My Tasks placement (already one row per person per task); nullable, so
nothing existing changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("my_task_placements", sa.Column("nudge_snoozed_until", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("my_task_placements", "nudge_snoozed_until")
