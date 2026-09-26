"""S3.5.2: the admin usage report — token/cost totals from ``llm_calls``, grouped by feature,
user and day. Read-only; never touches prompt or response bodies (``llm_calls`` doesn't keep
them, so there's nothing to leak here beyond counts and costs).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai.models import LlmCall
from momentum.ai.usage import month_start
from momentum.core.context import Ctx
from momentum.core.permissions import Action, require
from momentum.domain.users.models import User
from momentum.domain.workspace.service import effective_ai, get_ai_config

MAX_DAYS = 90


class UsageTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    errors: int


class UsageByFeature(UsageTotals):
    feature: str


class UsageByUser(UsageTotals):
    user_id: uuid.UUID | None
    user_name: str | None  # None: agent/system calls (no acting user)


class UsageByDay(UsageTotals):
    day: str  # ISO date


class UsageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    since: datetime
    month_spend_usd: Decimal
    monthly_budget_usd: float  # 0 = unlimited; the effective value (workspace override or env)
    by_feature: list[UsageByFeature]
    by_user: list[UsageByUser]
    by_day: list[UsageByDay]


def _totals(row: object) -> UsageTotals:
    return UsageTotals(
        calls=row.calls,  # type: ignore[attr-defined]
        tokens_in=row.tokens_in,  # type: ignore[attr-defined]
        tokens_out=row.tokens_out,  # type: ignore[attr-defined]
        cost_usd=row.cost_usd,  # type: ignore[attr-defined]
        errors=row.errors,  # type: ignore[attr-defined]
    )


async def get_usage_report(session: AsyncSession, ctx: Ctx, *, days: int = 30) -> UsageReport:
    require(ctx, Action.WORKSPACE_ADMIN)
    days = max(1, min(days, MAX_DAYS))
    since = datetime.now(UTC) - timedelta(days=days)
    base = select(
        func.count().label("calls"),
        func.coalesce(func.sum(LlmCall.tokens_in), 0).label("tokens_in"),
        func.coalesce(func.sum(LlmCall.tokens_out), 0).label("tokens_out"),
        func.coalesce(func.sum(LlmCall.cost_usd), 0).label("cost_usd"),
        func.count().filter(LlmCall.status != "ok").label("errors"),
    ).where(LlmCall.workspace_id == ctx.workspace_id, LlmCall.created_at >= since)

    by_feature_rows = (
        await session.execute(
            base.add_columns(LlmCall.feature).group_by(LlmCall.feature).order_by(LlmCall.feature)
        )
    ).all()
    by_user_rows = (
        await session.execute(
            base.add_columns(LlmCall.user_id, User.name)
            .join(User, User.id == LlmCall.user_id, isouter=True)
            .group_by(LlmCall.user_id, User.name)
            .order_by(func.coalesce(func.sum(LlmCall.cost_usd), 0).desc())
        )
    ).all()
    day = cast(LlmCall.created_at, Date)
    by_day_rows = (
        await session.execute(base.add_columns(day.label("day")).group_by(day).order_by(day))
    ).all()

    config = await get_ai_config(session, ctx.workspace_id)
    eff = effective_ai(ctx.settings, config)
    month_spend = await session.scalar(
        select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(
            LlmCall.workspace_id == ctx.workspace_id,
            LlmCall.created_at >= month_start(datetime.now(UTC)),
        )
    )

    return UsageReport(
        since=since,
        month_spend_usd=Decimal(month_spend or 0),
        monthly_budget_usd=eff.monthly_budget_usd,
        by_feature=[
            UsageByFeature(feature=r.feature, **_totals(r).model_dump()) for r in by_feature_rows
        ],
        by_user=[
            UsageByUser(user_id=r.user_id, user_name=r.name, **_totals(r).model_dump())
            for r in by_user_rows
        ],
        by_day=[UsageByDay(day=r.day.isoformat(), **_totals(r).model_dump()) for r in by_day_rows],
    )
