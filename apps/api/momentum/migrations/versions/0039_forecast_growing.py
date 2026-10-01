"""forecast status growing

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-01 18:00:00.000000

Phase 6.5 fix to S6.5.3: a forecast whose work arrives at least as fast as it is finished has
status ``growing`` (no end date) instead of a date at the simulation's ten-year cap. Widens the
status check constraint; no data changes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_forecasts_status"), "forecasts", type_="check")
    op.create_check_constraint(
        op.f("ck_forecasts_status"),
        "forecasts",
        "status in ('ok', 'done', 'no_history', 'growing')",
    )


def downgrade() -> None:
    op.execute("update forecasts set status = 'no_history' where status = 'growing'")
    op.drop_constraint(op.f("ck_forecasts_status"), "forecasts", type_="check")
    op.create_check_constraint(
        op.f("ck_forecasts_status"), "forecasts", "status in ('ok', 'done', 'no_history')"
    )
