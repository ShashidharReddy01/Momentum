"""Usage accounting for the gateway: the budget check before a call and the llm_calls row after.

Each row is written in its **own short transaction**, not the caller's: a request that later
rolls back (a failed apply, an AI preview's dry-run SAVEPOINT) still spent the tokens, so its
usage must still count toward the budget and show on the usage page.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai.errors import AgentBudgetExceeded, AIDisabled, BudgetExceeded, UserRateLimited
from momentum.ai.models import LlmCall
from momentum.core.context import Ctx
from momentum.domain.agents.models import Agent, AgentRun
from momentum.domain.workspace.service import AiConfig, get_ai_config


@dataclass(frozen=True)
class CallRecord:
    feature: str
    alias: str
    model: str
    status: str  # ok | error | budget_exceeded
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0
    error_code: str | None = None
    prompt_version: str | None = None
    agent_run_id: uuid.UUID | None = None


class UsageLog(Protocol):
    async def check_enabled(self, ctx: Ctx) -> None: ...

    async def check_budget(
        self, ctx: Ctx, *, agent_run_id: uuid.UUID | None = None, priced: bool = True
    ) -> None: ...

    async def record(self, ctx: Ctx, rec: CallRecord) -> None: ...


class NullUsageLog:
    """For callers with no workspace database (``momentum llm-check``): no budget, no rows."""

    async def check_enabled(self, ctx: Ctx) -> None:
        return None

    async def check_budget(
        self, ctx: Ctx, *, agent_run_id: uuid.UUID | None = None, priced: bool = True
    ) -> None:
        return None

    async def record(self, ctx: Ctx, rec: CallRecord) -> None:
        return None


def month_start(now: datetime) -> datetime:
    """Budgets reset at 00:00 UTC on the 1st (one workspace-wide boundary, not per-user)."""
    now = now.astimezone(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class DbUsageLog:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        monthly_budget_usd: float,
        user_calls_per_hour: int = 0,
    ) -> None:
        self._sf = session_factory
        self._budget = Decimal(str(monthly_budget_usd))
        self._per_hour = user_calls_per_hour

    async def month_spend(self, workspace_id: uuid.UUID, now: datetime | None = None) -> Decimal:
        since = month_start(now or datetime.now(UTC))
        async with self._sf() as session:
            total = await session.scalar(
                select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(
                    LlmCall.workspace_id == workspace_id, LlmCall.created_at >= since
                )
            )
        return Decimal(total or 0)

    async def _config(self, ctx: Ctx) -> AiConfig:
        async with self._sf() as session:
            return await get_ai_config(session, ctx.workspace_id)

    async def check_enabled(self, ctx: Ctx) -> None:
        """The admin switch (S3.5.2). ``LLM`` has already checked the environment's kill switch;
        this is the workspace override an admin can set on the AI settings page."""
        if (await self._config(ctx)).enabled is False:
            raise AIDisabled()

    async def _limit(self, ctx: Ctx) -> Decimal:
        override = (await self._config(ctx)).monthly_budget_usd
        return self._budget if override is None else Decimal(str(override))

    async def check_budget(
        self, ctx: Ctx, *, agent_run_id: uuid.UUID | None = None, priced: bool = True
    ) -> None:
        budget = await self._limit(ctx)
        if budget > 0:
            spent = await self.month_spend(ctx.workspace_id)
            if spent >= budget:
                raise BudgetExceeded(
                    f"This workspace has used ${spent:.2f} of its ${budget:.2f} monthly AI "
                    "budget. An admin can raise it.",
                )
        if agent_run_id is not None:
            await self._check_agent_budget(agent_run_id, priced=priced)
        elif self._per_hour > 0 and ctx.actor.id is not None and not ctx.actor.is_agent:
            await self._check_user_rate(ctx.actor.id)

    async def _check_user_rate(self, user_id: uuid.UUID) -> None:
        """Phase 7 S7.1.1: a person's own calls (not agents') in the last hour, so one runaway
        script or stuck tab can't spend the workspace's budget for 150 people."""
        since = datetime.now(UTC) - timedelta(hours=1)
        async with self._sf() as session:
            used = await session.scalar(
                select(func.count()).where(
                    LlmCall.user_id == user_id,
                    LlmCall.created_at >= since,
                    LlmCall.agent_run_id.is_(None),
                    LlmCall.status == "ok",
                )
            )
        if (used or 0) >= self._per_hour:
            raise UserRateLimited(
                f"You've made {used} AI requests in the last hour (the limit is {self._per_hour}). "
                "Try again in a little while."
            )

    async def agent_month_usage(
        self, agent_id: uuid.UUID, now: datetime | None = None
    ) -> tuple[Decimal, int]:
        """An agent's estimated spend and tokens (in + out) since 00:00 UTC on the 1st."""
        since = month_start(now or datetime.now(UTC))
        async with self._sf() as session:
            row = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(LlmCall.cost_usd), 0),
                        func.coalesce(func.sum(LlmCall.tokens_in + LlmCall.tokens_out), 0),
                    )
                    .join(AgentRun, AgentRun.id == LlmCall.agent_run_id)
                    .where(AgentRun.agent_id == agent_id, LlmCall.created_at >= since)
                )
            ).one()
        return Decimal(row[0] or 0), int(row[1] or 0)

    async def _check_agent_budget(self, agent_run_id: uuid.UUID, *, priced: bool) -> None:
        """S5.1.2 (kickoff Q4): an agent's own monthly cap. Dollars while its model is priced in
        MOMENTUM_LLM_PRICE_TABLE; otherwise tokens, so the cap means something before prices are
        set. A cap of 0 is unlimited, like the workspace budget."""
        async with self._sf() as session:
            agent = (
                await session.execute(
                    select(Agent)
                    .join(AgentRun, AgentRun.agent_id == Agent.id)
                    .where(AgentRun.id == agent_run_id)
                )
            ).scalar_one_or_none()
        if agent is None:
            return
        spent, tokens = await self.agent_month_usage(agent.id)
        if priced and agent.budget_monthly_usd > 0 and spent >= agent.budget_monthly_usd:
            raise AgentBudgetExceeded(
                f"{agent.name} has used ${spent:.2f} of its ${agent.budget_monthly_usd:.2f} "
                "monthly budget. An admin can raise it."
            )
        if not priced and agent.budget_monthly_tokens > 0 and tokens >= agent.budget_monthly_tokens:
            raise AgentBudgetExceeded(
                f"{agent.name} has used {tokens:,} of its {agent.budget_monthly_tokens:,} monthly "
                "tokens. An admin can raise it."
            )

    async def record(self, ctx: Ctx, rec: CallRecord) -> None:
        async with self._sf() as session, session.begin():
            session.add(
                LlmCall(
                    workspace_id=ctx.workspace_id,
                    feature=rec.feature,
                    alias=rec.alias,
                    model=rec.model,
                    prompt_version=rec.prompt_version,
                    user_id=None if ctx.actor.is_agent else ctx.actor.id,
                    agent_run_id=rec.agent_run_id,
                    tokens_in=rec.tokens_in,
                    tokens_out=rec.tokens_out,
                    cost_usd=rec.cost_usd,
                    latency_ms=rec.latency_ms,
                    status=rec.status,
                    error_code=rec.error_code,
                )
            )
