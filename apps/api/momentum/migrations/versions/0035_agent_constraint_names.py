"""agent constraint names

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-30 18:00:00.000000

Housekeeping: 0028 named the two agent unique constraints after their first column only
(``uq_agents_workspace_id``, ``uq_agent_runs_agent_id``), while the naming convention names every
column, so autogenerate kept proposing to drop and re-create them. Renamed to the convention's
names. A rename only: no data or index is touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMES = [
    ("agents", "uq_agents_workspace_id", "uq_agents_workspace_id_key"),
    ("agent_runs", "uq_agent_runs_agent_id", "uq_agent_runs_agent_id_dedupe_key"),
]


def upgrade() -> None:
    for table, old, new in RENAMES:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')


def downgrade() -> None:
    for table, old, new in RENAMES:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{new}" TO "{old}"')
