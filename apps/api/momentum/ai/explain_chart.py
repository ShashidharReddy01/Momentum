"""Phase 7.5 (spec §8): "Explain this chart" (a widget's menu).

The facts are the widget's own numbers as the viewer (``widget_data``, with the viewer's filters),
the previous period where the widget has one (a KPI's comparison, a line's bucket before the
last), and a drill sample (the tasks or projects behind the biggest mark). The ``default`` alias
explains changes and outliers; a paragraph is kept only if it cites a label, project, stage or task
from the facts and every number in it is in the facts. The sample comes back as "Open the tasks"
links. Nothing is stored.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.grounding import data_block, grounded, match_cites, numbers_in
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.core.context import Ctx
from momentum.core.errors import NotFound, ValidationFailed
from momentum.domain.dashboards import query_v2
from momentum.domain.dashboards import service as dashboards
from momentum.domain.dashboards.schemas import DrillAnyIn, QueryResultOut
from momentum.domain.dashboards.schemas_v2 import DashboardFilters

MAX_GROUPS = 15
SAMPLE = 8


class ExplainParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=600)
    cites: list[str] = Field(default_factory=list, max_length=10)


class ExplainDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraphs: list[ExplainParagraph] = Field(default_factory=list, max_length=5)


@dataclass
class Link:
    kind: str  # task | project
    id: uuid.UUID
    label: str


@dataclass
class Explanation:
    widget_id: uuid.UUID
    title: str
    paragraphs: list[ExplainParagraph]
    links: list[Link] = field(default_factory=list)
    sample_label: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    ai: bool = True


def _num(v: float | None) -> float | int | None:
    if v is None:
        return None
    return int(v) if float(v).is_integer() else round(v, 2)


def facts_of(title: str, r: QueryResultOut) -> dict[str, Any]:
    """The widget's result, compact, as the model sees it (no ids)."""
    f: dict[str, Any] = {
        "widget": title,
        "kind": r.kind,
        "what_it_counts": r.description,
        "measure": r.measure,
        "total": _num(r.total),
    }
    if r.value is not None:
        f["value"] = _num(r.value)
    if r.previous is not None:
        f["previous_period"] = _num(r.previous)
    if r.target is not None:
        f["target"] = _num(r.target)
    if r.groups:
        f["groups"] = [{"label": g.label, "value": _num(g.value)} for g in r.groups[:MAX_GROUPS]]
        if len(r.groups) > MAX_GROUPS:
            f["more_groups"] = len(r.groups) - MAX_GROUPS
    if r.stacks:
        labels = [g.label for g in r.groups[:MAX_GROUPS]]
        f["split"] = [
            {
                "label": s.label,
                "by_group": dict(zip(labels, [_num(v) for v in s.values], strict=False)),
            }
            for s in r.stacks[:8]
        ]
    if r.series:
        f["series"] = [
            {"from": p.start.isoformat(), "value": _num(p.value)} for p in r.series[-12:]
        ]
        if len(r.series) >= 2:
            f["last_bucket"] = _num(r.series[-1].value)
            f["bucket_before"] = _num(r.series[-2].value)
    if r.stages:
        f["stages"] = [
            {
                k: v
                for k, v in {
                    "stage": s.label,
                    "count": s.count,
                    "conversion_pct": round(100 * s.conversion) if s.conversion else None,
                    "median_days": s.median_days,
                    "p90_days": s.p90_days,
                    "target_days": s.target_days,
                    "past_target": s.breaches or None,
                }.items()
                if v is not None
            }
            for s in r.stages
        ]
    if r.rows:
        f["rows"] = [
            {k: v for k, v in row.items() if k in ("name", *r.columns) and v not in (None, "")}
            for row in r.rows[:10]
        ]
    if r.timeline:
        f["timeline"] = [
            {"date": t.date.isoformat(), "what": t.title, "project": t.project_name}
            for t in r.timeline[:12]
        ]
    if r.tasks:
        f["tasks"] = [{"key": t.key, "title": t.title} for t in r.tasks[:10]]
    if r.notes:
        f["notes"] = r.notes
    return f


def citables(f: dict[str, Any]) -> list[str]:
    out: list[str] = [f["widget"]]
    for g in f.get("groups") or []:
        out.append(g["label"])
    for s in f.get("split") or []:
        out.append(s["label"])
    for s in f.get("stages") or []:
        out.append(s["stage"])
    for r in f.get("rows") or []:
        if r.get("name"):
            out.append(str(r["name"]))
    for t in f.get("timeline") or []:
        out.append(t["project"])
    for t in [*(f.get("tasks") or []), *(f.get("sample") or [])]:
        out.append(t.get("key") or t.get("name") or "")
    return list(dict.fromkeys(x for x in out if x))


async def _sample(
    session: AsyncSession, ctx: Ctx, spec: Any, r: QueryResultOut, filters: DashboardFilters
) -> tuple[str | None, list[Link], list[dict[str, Any]]]:
    """The tasks or projects behind the biggest mark (or the whole widget)."""
    key: str | None = None
    if r.groups:
        key = max(r.groups, key=lambda g: g.value).key
    elif r.stages and getattr(spec, "entity", "") == "stage_events":
        biggest = max(r.stages, key=lambda s: s.count)
        key = biggest.option_id if biggest.count else None
    try:
        body = DrillAnyIn(query_spec=spec, key=key, limit=SAMPLE, filters=filters)
        drill = await query_v2.drill_any(session, ctx, body)
    except (ValidationError, ValidationFailed, NotFound, ValueError):
        return None, [], []
    links = [Link("task", t.id, f"{t.key} {t.title}") for t in drill.tasks[:SAMPLE]]
    links += [Link("project", p.id, p.name) for p in drill.projects[:SAMPLE]]
    sample: list[dict[str, Any]] = [{"key": t.key, "title": t.title} for t in drill.tasks[:SAMPLE]]
    sample += [{"name": p.name, "stage": p.stage} for p in drill.projects[:SAMPLE]]
    return drill.label, links, sample


def keep(draft: ExplainDraft, f: dict[str, Any]) -> list[ExplainParagraph]:
    allowed = citables(f)
    known = numbers_in(f)
    out: list[ExplainParagraph] = []
    for p in draft.paragraphs:
        text = " ".join(p.text.split())
        cites = match_cites(p.cites, allowed)
        if cites and grounded(text, known):
            out.append(ExplainParagraph(text=text, cites=cites))
    return out


async def explain(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    widget_id: uuid.UUID,
    *,
    filters: DashboardFilters | None = None,
) -> Explanation:
    w, d, _ = await dashboards.get_widget(session, ctx, widget_id)
    if w.kind == "note":
        raise ValidationFailed("A note has no numbers to explain")
    applied = filters if filters is not None else dashboards.saved_filters(d)
    r = await dashboards.widget_data(session, ctx, widget_id, filters=applied)
    spec = dashboards.SPEC.validate_python(w.query_spec)
    label, links, sample = await _sample(session, ctx, spec, r, applied)
    f = facts_of(w.title, r)
    if sample:
        f["sample"] = sample
        f["sample_is"] = label
    if not r.total and not r.value and not r.rows and not r.timeline:
        return Explanation(
            w.id,
            w.title,
            [ExplainParagraph(text="This chart shows nothing yet, so there's nothing to explain.")],
            links,
            label,
            f,
            ai=False,
        )
    prompt = prompts.load("explain_chart")
    draft = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=data_block("widget_data", f, citables(f), widget=w.title),
        schema=ExplainDraft,
        description="Submit the explanation.",
    )
    return Explanation(w.id, w.title, keep(draft, f), links, label, f)
