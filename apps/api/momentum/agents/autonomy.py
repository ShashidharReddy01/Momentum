"""S5.1.4: automatic demotion (agents.md §5). Daily: an agent at ``auto`` whose own changes were
undone more than 10% of the time in the last week goes back to ``confirm``, and the workspace
admins are told why. Promotion is never automatic: an admin decides, when the stats allow it."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents.runtime import alert_admins
from momentum.agents.triggers import agent_ctx
from momentum.core.context import Actor, Ctx
from momentum.core.settings import Settings
from momentum.domain.agents import service
from momentum.domain.agents.models import Agent
from momentum.domain.agents.stats import DEMOTION_UNDO_RATE, agent_stats, should_demote
from momentum.domain.users.models import User


@dataclass
class DemotionRun:
    checked: int = 0
    demoted: list[str] = field(default_factory=list)


async def run_demotions(session: AsyncSession, settings: Settings) -> DemotionRun:
    out = DemotionRun()
    agents = (await session.execute(select(Agent).where(Agent.autonomy == "auto"))).scalars()
    for agent in list(agents):
        out.checked += 1
        stats = await agent_stats(session, agent)
        if not should_demote(agent, stats):
            continue
        reason = (
            f"{stats.auto_undone_7d} of the {stats.auto_applied_7d} changes it made on its own "
            f"this week were undone (over {int(DEMOTION_UNDO_RATE * 100)}%)"
        )
        system = Ctx(
            actor=Actor(id=None, workspace_id=agent.workspace_id, role="admin"),
            settings=settings,
            via="system",
        )
        await service.demote(session, system, agent, reason)
        account = await session.get(User, agent.user_id)
        if account is not None:
            await alert_admins(
                session,
                agent_ctx(agent, account, settings),
                agent,
                f"{agent.name} now asks before changing things",
                reason,
            )
        out.demoted.append(agent.key)
    return out
