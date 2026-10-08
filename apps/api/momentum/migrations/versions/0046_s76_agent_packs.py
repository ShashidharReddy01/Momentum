"""s76 agent packs

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-08 18:00:00

Phase 7.6 S76-01 (spec §3.3; ADR-0012): agents can be **packs**. ``agents.kind`` gains
``pack``; ``agents.pack_key`` / ``agents.pack_version`` record which pack (and which version of it)
an installed agent came from; ``agents.source`` gains ``pack``. The plan numbered this "0045,
part 1", but 0045 was already Phase 7.5's ``report_runs``: Phase 7.6's migrations are numbered
from 0046, one per slice that needs one.

Only columns and check constraints are added; no row is rewritten (every existing agent keeps
``kind`` llm/handler and null pack columns).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("pack_key", sa.String(length=60), nullable=True))
    op.add_column("agents", sa.Column("pack_version", sa.String(length=20), nullable=True))
    op.drop_constraint(op.f("ck_agents_kind"), "agents", type_="check")
    op.create_check_constraint(
        op.f("ck_agents_kind"), "agents", "kind in ('llm', 'handler', 'pack')"
    )
    op.create_check_constraint(
        op.f("ck_agents_pack"),
        "agents",
        "(kind = 'pack') = (pack_key is not null and pack_version is not null)",
    )
    op.drop_constraint(op.f("ck_agents_source"), "agents", type_="check")
    op.create_check_constraint(
        op.f("ck_agents_source"), "agents", "source in ('starter', 'host', 'custom', 'pack')"
    )


def downgrade() -> None:
    # Pack agents can't exist under the old constraints: refuse rather than delete them.
    bind = op.get_bind()
    n = bind.execute(sa.text("select count(*) from agents where kind = 'pack'")).scalar_one()
    if n:
        raise RuntimeError(
            f"{n} pack agent(s) exist; disable and remove them before downgrading below 0046"
        )
    op.drop_constraint(op.f("ck_agents_source"), "agents", type_="check")
    op.create_check_constraint(
        op.f("ck_agents_source"), "agents", "source in ('starter', 'host', 'custom')"
    )
    op.drop_constraint(op.f("ck_agents_pack"), "agents", type_="check")
    op.drop_constraint(op.f("ck_agents_kind"), "agents", type_="check")
    op.create_check_constraint(op.f("ck_agents_kind"), "agents", "kind in ('llm', 'handler')")
    op.drop_column("agents", "pack_version")
    op.drop_column("agents", "pack_key")
