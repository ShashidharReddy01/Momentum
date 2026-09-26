"""Usage accounting for the gateway: the budget check before a call and the llm_calls row after.

Each row is written in its **own short transaction**, not the caller's: a request that later
rolls back (a failed apply, an AI preview's dry-run SAVEPOINT) still spent the tokens, so its
usage must still count toward the budget and show on the usage page.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from momentum.ai.errors import BudgetExceeded
from momentum.ai.models import LlmCall
from momentum.core.context import Ctx


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
    async def check_budget(self, ctx: Ctx) -> None: ...

    async def record(self, ctx: Ctx, rec: CallRecord) -> None: ...


class NullUsageLog:
    """For callers with no workspace database (``momentum llm-check``): no budget, no rows."""

    async def check_budget(self, ctx: Ctx) -> None:
        return None

    async def record(self, ctx: Ctx, rec: CallRecord) -> None:
        return None


def month_start(now: datetime) -> datetime:
    """Budgets reset at 00:00 UTC on the 1st (one workspace-wide boundary, not per-user)."""
    now = now.astimezone(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class DbUsageLog:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], monthly_budget_usd: float
    ) -> None:
        self._sf = session_factory
        self._budget = Decimal(str(monthly_budget_usd))

    async def month_spend(self, workspace_id: uuid.UUID, now: datetime | None = None) -> Decimal:
        since = month_start(now or datetime.now(UTC))
        async with self._sf() as session:
            total = await session.scalar(
                select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(
                    LlmCall.workspace_id == workspace_id, LlmCall.created_at >= since
                )
            )
        return Decimal(total or 0)

    async def check_budget(self, ctx: Ctx) -> None:
        if self._budget <= 0:
            return
        spent = await self.month_spend(ctx.workspace_id)
        if spent >= self._budget:
            raise BudgetExceeded(
                f"This workspace has used ${spent:.2f} of its ${self._budget:.2f} monthly AI "
                "budget. An admin can raise it.",
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
