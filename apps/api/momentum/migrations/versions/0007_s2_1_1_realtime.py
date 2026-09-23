"""s2_1_1 realtime: consumer offsets, outbox replay index

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consumer_offsets",
        sa.Column("consumer", sa.String(length=200), nullable=False),
        sa.Column("last_event_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("consumer", name=op.f("pk_consumer_offsets")),
    )
    # Replay-on-reconnect scans events_outbox for one workspace above a starting id.
    op.create_index(
        "ix_events_outbox_workspace_id",
        "events_outbox",
        ["workspace_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_events_outbox_workspace_id", table_name="events_outbox")
    op.drop_table("consumer_offsets")
