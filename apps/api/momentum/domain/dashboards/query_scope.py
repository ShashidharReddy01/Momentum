"""Phase 7.5 (spec §7.1, §7.3): which projects a v2 widget looks at, as the viewer.

A scope is the visible projects, narrowed by a portfolio (its manual list or its rule), owners
(``"me"`` is the viewer), project-field conditions (a people field's ``"me"`` too), templates,
teams and status. Everything else in a v2 query starts from here, so visibility is applied first.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.domain.access import visible_projects_clause
from momentum.domain.fields.models import FieldDef
from momentum.domain.portfolios.membership import condition_clause, members_clause
from momentum.domain.portfolios.models import Portfolio
from momentum.domain.projects.models import Project
from momentum.domain.tasks.models import Task, TaskProject

NO_PROJECT = uuid.UUID(int=0)  # an id no project has: "an empty scope", never "every project"


def me(values: list[Any], ctx: Ctx) -> list[Any]:
    """``"me"`` → the viewer's id (as text, like stored people values)."""
    return [str(ctx.actor.id) if v == "me" else v for v in values]


def resolve_condition(cond: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    value = cond.get("value")
    if isinstance(value, list):
        value = me(value, ctx)
    elif value == "me":
        value = [str(ctx.actor.id)]
    return {**cond, "field_id": str(cond["field_id"]), "value": value}


@dataclass
class Scope:
    projects: list[Project]
    portfolio: Portfolio | None
    stage_field: FieldDef | None

    @property
    def ids(self) -> list[uuid.UUID]:
        return [p.id for p in self.projects] or [NO_PROJECT]


async def scope_projects(
    session: AsyncSession,
    ctx: Ctx,
    *,
    portfolio_id: uuid.UUID | None = None,
    owner: list[str] | None = None,
    assignee: list[str] | None = None,
    fields: list[dict[str, Any]] | None = None,
    template_ids: list[uuid.UUID] | None = None,
    team_ids: list[uuid.UUID] | None = None,
    status: list[str] | None = None,
    include_completed: bool = True,
) -> Scope:
    from momentum.domain.portfolios.service import get_portfolio

    q = select(Project).where(
        visible_projects_clause(ctx), Project.is_template.is_(False), Project.deleted_at.is_(None)
    )
    portfolio: Portfolio | None = None
    stage_field: FieldDef | None = None
    if portfolio_id is not None:
        portfolio = await get_portfolio(session, ctx, portfolio_id)
        q = q.where(members_clause(portfolio))
        if portfolio.stage_field_id is not None:
            stage_field = await session.get(FieldDef, portfolio.stage_field_id)
    else:
        q = q.where(Project.archived_at.is_(None))
    owners = [uuid.UUID(str(x)) for x in me(list(owner or []), ctx) if x]
    if owners:
        q = q.where(Project.owner_id.in_(owners))
    assignees = [uuid.UUID(str(x)) for x in me(list(assignee or []), ctx) if x]
    if assignees:
        q = q.where(
            Project.id.in_(
                select(TaskProject.project_id)
                .join(Task, Task.id == TaskProject.task_id)
                .where(
                    Task.assignee_id.in_(assignees),
                    Task.completed_at.is_(None),
                    Task.deleted_at.is_(None),
                )
            )
        )
    for cond in fields or []:
        q = q.where(condition_clause(resolve_condition(cond, ctx)))
    if template_ids:
        q = q.where(Project.template_id.in_(template_ids))
    if team_ids:
        q = q.where(Project.team_id.in_(team_ids))
    named = [s for s in status or [] if s != "none"]
    if status:
        q = q.where(
            or_(
                Project.status.in_(named),
                *([Project.status.is_(None)] if "none" in status else []),
            )
        )
    if not include_completed:
        q = q.where(or_(Project.status.is_(None), Project.status != "complete"))
    projects = list((await session.execute(q.order_by(Project.name, Project.id))).scalars())
    return Scope(projects, portfolio, stage_field)


def period_window(
    period: str | None, start: str | None, end: str | None, today: date
) -> int | None:
    """Days a dashboard period covers, ending today (custom: its own length)."""
    if period == "this_week":
        return today.weekday() + 1
    if period == "this_month":
        return today.day
    if period == "last_30_days":
        return 30
    if period == "this_quarter":
        first = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        return (today - first).days + 1
    if period == "custom" and start and end:
        return max(1, (date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
    return None


def period_bounds(period: str | None, today: date) -> tuple[date, date] | None:
    """A calendar period's first day and the first day of the one before it (a KPI compares
    the two): this week from Monday, this month, this quarter, the last 30 days."""
    if period == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, start - timedelta(days=7)
    if period == "this_month":
        start = today.replace(day=1)
        return start, (start - timedelta(days=1)).replace(day=1)
    if period == "this_quarter":
        start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        last = start - timedelta(days=1)
        return start, date(last.year, 3 * ((last.month - 1) // 3) + 1, 1)
    if period == "last_30_days":
        start = today - timedelta(days=29)
        return start, start - timedelta(days=30)
    return None


def day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)


def days_between(a: datetime, b: datetime) -> float:
    return (b - a) / timedelta(days=1)
