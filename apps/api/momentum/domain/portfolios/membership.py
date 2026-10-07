"""Phase 7.5 (spec §5.2): which projects belong to a portfolio, as SQL.

A manual portfolio lists its projects (``portfolio_items``). A rule portfolio computes them:
``{template_ids[], team_ids[], project_ids[], project_field_conditions[], include_completed,
include_archived}``; every given criterion must hold (an empty list means "any"). Visibility is
applied separately by the caller (``visible_projects_clause``), so a rule never reveals a
project the viewer can't see.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Numeric,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    literal_column,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.domain.fields.models import ProjectFieldValue
from momentum.domain.portfolios.models import Portfolio, PortfolioItem
from momentum.domain.projects.models import Project


def _uuids(values: Any) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for v in values or []:
        try:
            out.append(uuid.UUID(str(v)))
        except ValueError:
            continue
    return out


def condition_clause(cond: dict[str, Any]) -> ColumnElement[bool]:
    """One project-field condition: ``{field_id, op: is|is_not|any|empty|set|gte|lte, value}``.
    ``gte`` / ``lte`` (S75-10, "going live in November") compare a date field's ISO day or a
    number field's value, inclusive."""
    fid = _uuids([cond.get("field_id")])
    if not fid:
        return false()
    op = cond.get("op", "is")
    value = cond.get("value")
    has = select(ProjectFieldValue.project_id).where(ProjectFieldValue.field_id == fid[0])
    if op == "set":
        return Project.id.in_(has)
    if op == "empty":
        return Project.id.not_in(has)
    if op in ("is", "is_not"):
        match = has.where(ProjectFieldValue.value == _json(value))
        return Project.id.in_(match) if op == "is" else Project.id.not_in(match)
    if op == "any":  # one of several single-select options, or a multi-select containing one
        values = value if isinstance(value, list) else [value]
        return Project.id.in_(
            has.where(
                or_(
                    *(ProjectFieldValue.value == _json(v) for v in values),
                    *(ProjectFieldValue.value.contains([v]) for v in values),
                )
            )
        )
    if op in ("gte", "lte"):
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            return false()
        raw = ProjectFieldValue.value
        as_text = raw.op("#>>")(literal_column("'{}'"))  # a JSON scalar as text
        right: Any
        if isinstance(value, str):  # an ISO date: same-length strings compare in date order
            left: Any = case((func.jsonb_typeof(raw) == "string", as_text), else_=None)
            right = value[:10]
        else:  # the cast only runs on numbers (CASE keeps Postgres from casting text)
            left = case((func.jsonb_typeof(raw) == "number", cast(as_text, Numeric)), else_=None)
            right = value
        return Project.id.in_(has.where(left >= right if op == "gte" else left <= right))
    return false()


def _json(v: Any) -> Any:
    return cast(literal(json.dumps(v)), JSONB)


def rule_clause(rule: dict[str, Any] | None) -> ColumnElement[bool]:
    rule = rule or {}
    parts: list[ColumnElement[bool]] = [
        Project.deleted_at.is_(None),
        Project.is_template.is_(False),
    ]
    templates = _uuids(rule.get("template_ids"))
    if templates:
        parts.append(Project.template_id.in_(templates))
    teams = _uuids(rule.get("team_ids"))
    if teams:
        parts.append(Project.team_id.in_(teams))
    explicit = _uuids(rule.get("project_ids"))
    if explicit:
        parts.append(Project.id.in_(explicit))
    if not rule.get("include_archived"):
        parts.append(Project.archived_at.is_(None))
    if not rule.get("include_completed"):  # a project is complete when its status says so
        parts.append(or_(Project.status.is_(None), Project.status != "complete"))
    for cond in rule.get("project_field_conditions") or []:
        if isinstance(cond, dict):
            parts.append(condition_clause(cond))
    if not (templates or teams or explicit or rule.get("project_field_conditions")):
        parts.append(false())  # an empty rule matches nothing, never the whole workspace
    return and_(*parts)


def members_clause(portfolio: Portfolio) -> ColumnElement[bool]:
    """Projects in the portfolio (before visibility)."""
    if portfolio.kind == "rule":
        return rule_clause(portfolio.rule)
    return Project.id.in_(
        select(PortfolioItem.project_id).where(PortfolioItem.portfolio_id == portfolio.id)
    )


async def portfolio_ids_containing(session: AsyncSession, project: Project) -> list[uuid.UUID]:
    """Every live portfolio that contains this project (for event channels). Not filtered by
    anyone's visibility: a channel only notifies; readers refetch as themselves."""
    manual = (
        await session.execute(
            select(PortfolioItem.portfolio_id)
            .join(Portfolio, Portfolio.id == PortfolioItem.portfolio_id)
            .where(PortfolioItem.project_id == project.id, Portfolio.deleted_at.is_(None))
        )
    ).scalars()
    out = set(manual)
    rules = (
        await session.execute(
            select(Portfolio).where(
                Portfolio.workspace_id == project.workspace_id,
                Portfolio.kind == "rule",
                Portfolio.deleted_at.is_(None),
            )
        )
    ).scalars()
    for p in rules:
        hit = (
            await session.execute(
                select(Project.id).where(Project.id == project.id, rule_clause(p.rule))
            )
        ).first()
        if hit is not None:
            out.add(p.id)
    return sorted(out)
