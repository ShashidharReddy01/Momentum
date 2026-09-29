"""S5.1.4: an agent's track record, for autonomy promotion and demotion (agents.md §5) and for
its budget panel.

- **Promotion** ``confirm → auto`` (admins only): at least 85% of its last 30 decided proposals
  accepted, and none of its changes undone in the last 14 days. Fewer than 30 decided proposals
  is not enough evidence yet.
- **Demotion** ``auto → confirm`` (automatic, daily): more than 10% of the changes it applied on
  its own in the last 7 days were undone.

``ai_actions`` and ``llm_calls`` belong to the AI layer, which the domain doesn't import, so they
are read through lightweight table constructs (tables resolve through the ``search_path``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import column, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.activity import Activity
from momentum.domain.agents.models import Agent, AgentRun

PROMOTION_SAMPLE = 30
PROMOTION_RATE = 0.85
PROMOTION_QUIET_DAYS = 14
DEMOTION_WINDOW_DAYS = 7
DEMOTION_UNDO_RATE = 0.10

_actions = table(
    "ai_actions",
    column("id"),
    column("source"),
    column("source_id"),
    column("state"),
    column("decided_by"),
    column("decided_at"),
    column("created_at"),
)
_calls = table(
    "llm_calls",
    column("agent_run_id"),
    column("cost_usd"),
    column("tokens_in"),
    column("tokens_out"),
    column("created_at"),
)
DECIDED = ("applied", "undone", "rejected", "expired")
ACCEPTED = ("applied", "undone")


@dataclass
class AgentStats:
    decided: int
    accepted: int
    undos_14d: int
    auto_applied_7d: int
    auto_undone_7d: int
    month_usd: Decimal
    month_tokens: int
    eligible_for_auto: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def acceptance_rate(self) -> float | None:
        return self.accepted / self.decided if self.decided else None

    @property
    def undo_rate_7d(self) -> float | None:
        return self.auto_undone_7d / self.auto_applied_7d if self.auto_applied_7d else None


def _month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def agent_stats(
    session: AsyncSession, agent: Agent, now: datetime | None = None
) -> AgentStats:
    now = now or datetime.now(UTC)
    runs = select(AgentRun.id).where(AgentRun.agent_id == agent.id).scalar_subquery()
    mine = (_actions.c.source == "agent") & _actions.c.source_id.in_(runs)
    # proposals a person decided (or let expire): not the agent's own auto-applied actions
    proposal = mine & (_actions.c.decided_by.is_(None) | (_actions.c.decided_by != agent.user_id))
    last = (
        select(_actions.c.state)
        .where(proposal, _actions.c.state.in_(DECIDED))
        .order_by(func.coalesce(_actions.c.decided_at, _actions.c.created_at).desc())
        .limit(PROMOTION_SAMPLE)
    )
    states = list((await session.execute(last)).scalars())
    action_ids = select(_actions.c.id).where(mine).scalar_subquery()
    undos = await session.scalar(
        select(func.count(func.distinct(Activity.ai_action_id))).where(
            Activity.ai_action_id.in_(action_ids),
            Activity.undone_at >= now - timedelta(days=PROMOTION_QUIET_DAYS),
        )
    )
    week = now - timedelta(days=DEMOTION_WINDOW_DAYS)
    auto = mine & (_actions.c.decided_by == agent.user_id) & (_actions.c.decided_at >= week)
    auto_applied = await session.scalar(
        select(func.count()).select_from(_actions).where(auto, _actions.c.state.in_(ACCEPTED))
    )
    auto_undone = await session.scalar(
        select(func.count()).select_from(_actions).where(auto, _actions.c.state == "undone")
    )
    usage = (
        await session.execute(
            select(
                func.coalesce(func.sum(_calls.c.cost_usd), 0),
                func.coalesce(func.sum(_calls.c.tokens_in + _calls.c.tokens_out), 0),
            ).where(_calls.c.agent_run_id.in_(runs), _calls.c.created_at >= _month_start(now))
        )
    ).one()
    decided = len(states)
    accepted = sum(1 for s in states if s in ACCEPTED)
    stats = AgentStats(
        decided=decided,
        accepted=accepted,
        undos_14d=int(undos or 0),
        auto_applied_7d=int(auto_applied or 0),
        auto_undone_7d=int(auto_undone or 0),
        month_usd=Decimal(usage[0] or 0),
        month_tokens=int(usage[1] or 0),
        eligible_for_auto=False,
    )
    if decided < PROMOTION_SAMPLE:
        stats.reasons.append(f"Needs {PROMOTION_SAMPLE} decided proposals to judge (has {decided})")
    elif accepted / decided < PROMOTION_RATE:
        stats.reasons.append(
            f"Acceptance {accepted}/{decided} is below {int(PROMOTION_RATE * 100)}%"
        )
    if stats.undos_14d:
        stats.reasons.append(f"{stats.undos_14d} of its changes were undone in the last 14 days")
    stats.eligible_for_auto = not stats.reasons
    return stats


def should_demote(agent: Agent, stats: AgentStats) -> bool:
    rate = stats.undo_rate_7d
    return agent.autonomy == "auto" and rate is not None and rate > DEMOTION_UNDO_RATE
