"""Phase 7.5 (spec §7.5): role dashboard templates (``templates/*.yaml``, data) and binding them.

A template names what it needs instead of ids, as ``"$…"`` strings anywhere in its filters and
widget specs:

- ``$portfolio``: the portfolio it's bound to; ``$stagefield``: that portfolio's stage field;
- ``$stage:<label>``: a stage (an option of the stage field); ``$stages:<a>..<b>``: the stages
  from a to b in lifecycle order (spliced into the list it sits in);
- ``$pf:<name>`` / ``$tf:<name>``: a project / task field, by name (case-insensitive);
- ``$opt:<field>:<label>`` / ``$topt:<field>:<label>``: an option of a project / task field;
- ``field:$pf:<name>`` (a table column): ``field:<id>``.

Binding never fails silently: a widget with a name that doesn't bind is dropped with a note saying
which name, and so is a filter. The bound specs then pass the same validation as any widget.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.domain.dashboards import query_v2
from momentum.domain.dashboards.schemas_v2 import AnySpec, DashboardFilters, check_any
from momentum.domain.fields.models import FieldDef
from momentum.domain.portfolios.models import Portfolio

TEMPLATES_DIR = Path(__file__).parent / "templates"
ORDER = (
    "sales",
    "discovery",
    "contracts",
    "implementation_lead",
    "implementation_consultant",
    "golive_support",
    "leadership",
)
SPEC = TypeAdapter[Any](AnySpec)


@cache
def load(key: str) -> dict[str, Any]:
    if key not in ORDER:
        raise NotFound("Dashboard template not found")
    data: dict[str, Any] = yaml.safe_load((TEMPLATES_DIR / f"{key}.yaml").read_text("utf-8"))
    return data


def catalog() -> list[dict[str, Any]]:
    out = []
    for key in ORDER:
        t = load(key)
        out.append(
            {
                "key": key,
                "name": t["name"],
                "description": t.get("description", ""),
                "persona": t.get("persona", ""),
                "widgets": [w["title"] for w in t["widgets"]],
            }
        )
    return out


class Missing(Exception):
    """A name the workspace doesn't have."""


@dataclass
class Binder:
    portfolio: Portfolio
    stage: FieldDef | None
    project_fields: dict[str, FieldDef]
    task_fields: dict[str, FieldDef]

    def _field(self, name: str, task: bool) -> FieldDef:
        f = (self.task_fields if task else self.project_fields).get(name.strip().lower())
        if f is None:
            raise Missing(f'no {"task" if task else "project"} field named "{name}"')
        return f

    @staticmethod
    def _option(f: FieldDef, label: str) -> str:
        for o in f.options or []:
            if isinstance(o, dict) and str(o.get("label", "")).lower() == label.strip().lower():
                return str(o["id"])
        raise Missing(f'no "{label}" in {f.name}')

    def _stages(self) -> tuple[FieldDef, list[dict[str, Any]]]:
        if self.stage is None:
            raise Missing("the portfolio has no stage field")
        return self.stage, [o for o in self.stage.options or [] if isinstance(o, dict)]

    def one(self, s: str) -> Any:
        if s.startswith("field:$"):
            return f"field:{self.one(s.removeprefix('field:'))}"
        if s == "$portfolio":
            return str(self.portfolio.id)
        if s == "$stagefield":
            return str(self._stages()[0].id)
        kind, _, rest = s[1:].partition(":")
        if kind == "stage":
            return self._option(self._stages()[0], rest)
        if kind == "stages":
            f, opts = self._stages()
            a, _, b = rest.partition("..")
            ids = [str(o["id"]) for o in opts]
            lo, hi = ids.index(self._option(f, a)), ids.index(self._option(f, b))
            if lo > hi:
                raise Missing(f"{a} comes after {b}")
            return ids[lo : hi + 1]
        if kind in ("pf", "tf"):
            return str(self._field(rest, kind == "tf").id)
        if kind in ("opt", "topt"):
            name, _, label = rest.rpartition(":")
            return self._option(self._field(name, kind == "topt"), label)
        raise Missing(f'unknown binding "{s}"')

    def bind(self, v: Any) -> Any:
        if isinstance(v, str) and (v.startswith("$") or v.startswith("field:$")):
            return self.one(v)
        if isinstance(v, list):
            out: list[Any] = []
            for x in v:
                b = self.bind(x)
                if isinstance(x, str) and x.startswith("$stages:"):
                    out.extend(b)
                else:
                    out.append(b)
            return out
        if isinstance(v, dict):
            return {k: self.bind(x) for k, x in v.items()}
        return v


@dataclass
class BoundWidget:
    kind: str
    title: str
    size: str
    spec: Any


@dataclass
class Bound:
    key: str
    name: str
    description: str
    filters: DashboardFilters
    widgets: list[BoundWidget] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


async def _fields(session: AsyncSession, ctx: Ctx, applies_to: str) -> dict[str, FieldDef]:
    rows = (
        await session.execute(
            select(FieldDef)
            .where(
                FieldDef.workspace_id == ctx.workspace_id,
                FieldDef.applies_to == applies_to,
                FieldDef.deleted_at.is_(None),
            )
            .order_by(FieldDef.created_at)
        )
    ).scalars()
    out: dict[str, FieldDef] = {}
    for f in rows:
        out.setdefault(f.name.strip().lower(), f)  # the oldest of a name wins
    return out


async def bind(session: AsyncSession, ctx: Ctx, key: str, portfolio_id: uuid.UUID) -> Bound:
    """The template with every name bound for this workspace and portfolio, as the viewer."""
    from momentum.domain.portfolios.service import get_portfolio

    t = load(key)
    p = await get_portfolio(session, ctx, portfolio_id)
    stage = await session.get(FieldDef, p.stage_field_id) if p.stage_field_id else None
    b = Binder(
        p,
        stage if stage is not None and stage.deleted_at is None else None,
        await _fields(session, ctx, "project"),
        await _fields(session, ctx, "task"),
    )
    notes: list[str] = []
    raw_filters = dict(t.get("filters") or {})
    filters: dict[str, Any] = {}
    for k, v in raw_filters.items():
        if k == "fields":
            kept = []
            for cond in v:
                try:
                    kept.append(b.bind(cond))
                except Missing as e:
                    notes.append(f"Left out a dashboard filter: {e}.")
            filters[k] = kept
        else:
            filters[k] = b.bind(v)
    out = Bound(
        key=key,
        name=str(t["name"]),
        description=str(t.get("description", "")),
        filters=DashboardFilters.model_validate(filters),
    )
    for w in t["widgets"]:
        try:
            spec = SPEC.validate_python(b.bind(w["spec"]))
            check_any(w["kind"], spec)
        except Missing as e:
            notes.append(f'Dropped "{w["title"]}": {e}.')
            continue
        except (ValidationError, ValueError) as e:  # a template bug, or a field of the wrong type
            notes.append(f'Dropped "{w["title"]}": {_reason(e)}')
            continue
        try:
            await query_v2.check_any(session, ctx, spec)
        except (ValidationFailed, NotFound) as e:  # e.g. the portfolio has no stage field
            notes.append(f'Dropped "{w["title"]}": {e.detail}.')
            continue
        out.widgets.append(BoundWidget(w["kind"], w["title"], w.get("size", "md"), spec))
    out.notes = notes
    if not out.widgets:
        raise ValidationFailed(
            "None of this template's widgets fit this portfolio", code="template_unbound"
        )
    return out


def _reason(e: Exception) -> str:
    if isinstance(e, ValidationError):
        first = e.errors()[0]
        return str(first.get("msg", "invalid"))
    return str(e)
