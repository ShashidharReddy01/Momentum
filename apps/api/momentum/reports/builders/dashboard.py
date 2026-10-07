"""Phase 7.5 (spec §6.2): ``dashboard``: each widget with its numbers, in order, run as the
requester with the dashboard's saved filters (the same ``run_any`` the page uses), plus the
filters used."""

from __future__ import annotations

from typing import Any

from momentum.domain.dashboards import query_v2
from momentum.domain.dashboards.schemas import QueryResultOut
from momentum.domain.dashboards.service import get_dashboard, saved_filters, widget_spec, widgets_of
from momentum.reports.builders.common import BuildContext, day
from momentum.reports.document import (
    Callout,
    Chart,
    Heading,
    Kpi,
    KPIRow,
    Paragraph,
    ReportDocument,
    Table,
    TaskItem,
    TaskList,
)

AGING = ["0-7d", "8-14d", "15-30d", "31-60d", "60d+"]


def _num(r: QueryResultOut, v: float | None) -> str:
    if v is None:
        return "—"
    if r.measure in ("avg_progress", "progress_avg"):
        return f"{round(v * 100)}%"
    if r.measure == "sum_estimate":
        return f"{round(v / 60, 1)}h"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def _filters_text(f: Any, names: dict[str, str]) -> str:
    parts = []
    if f.portfolio_id:
        parts.append(f"portfolio {names.get(str(f.portfolio_id), 'chosen')}")
    if f.period:
        parts.append(str(f.period).replace("_", " "))
    if "me" in f.owner:
        parts.append("projects the viewer owns")
    if "me" in f.assignee:
        parts.append("assigned to the viewer")
    if f.fields:
        parts.append(f"{len(f.fields)} project field condition(s)")
    return ", ".join(parts) if parts else "none"


async def build_dashboard(bc: BuildContext) -> ReportDocument:
    from momentum.domain.portfolios.models import Portfolio

    assert bc.spec.scope.dashboard_id is not None
    d, _editable = await get_dashboard(bc.session, bc.ctx, bc.spec.scope.dashboard_id)
    filters = saved_filters(d)
    names: dict[str, str] = {}
    if filters.portfolio_id:
        p = await bc.session.get(Portfolio, filters.portfolio_id)
        if p is not None:
            names[str(p.id)] = p.name
    doc = bc.doc(d.name, f"Dashboard, {day(bc.today)}")
    doc.add(Paragraph(f"Filters used: {_filters_text(filters, names)}."))
    facts: list[dict[str, Any]] = []
    for w in await widgets_of(bc.session, d):
        r = await query_v2.run_any(
            bc.session, bc.ctx, w.kind, widget_spec(w), project_id=d.project_id, filters=filters
        )
        doc.add(Heading(w.title, 2))
        if r.description and w.kind != "note":
            doc.add(Paragraph(r.description))
        if w.kind in ("count", "kpi"):
            delta = None
            if r.previous is not None and r.value is not None:
                delta = f"{_num(r, r.previous)} the period before"
            doc.add(KPIRow([Kpi(w.title, _num(r, r.value), r.value, delta)]))
        elif w.kind == "note":
            doc.add(Paragraph(r.text or ""))
        elif r.groups and w.kind in ("bar", "donut", "stacked_bar"):
            doc.add(
                Chart(
                    w.title,
                    "donut" if w.kind == "donut" else "bar",
                    [g.label for g in r.groups],
                    [g.value for g in r.groups],
                ),
                Table(w.title, ["Group", "Value"], [[g.label, g.value] for g in r.groups]),
            )
        elif r.series:
            doc.add(
                Chart(
                    w.title,
                    "line",
                    [p.start.isoformat() for p in r.series],
                    [p.value for p in r.series],
                ),
                Table(
                    w.title, ["From", "To", "Value"], [[p.start, p.end, p.value] for p in r.series]
                ),
            )
        elif r.tasks:
            doc.add(
                TaskList(
                    w.title,
                    [
                        TaskItem(
                            t.key, t.title, t.assignee_name, t.due_on, t.completed_at is not None
                        )
                        for t in r.tasks
                    ],
                )
            )
        elif r.rows:
            cols = r.columns or ["name"]
            doc.add(
                Table(
                    w.title,
                    [
                        c.replace("_", " ").capitalize() if not c.startswith("field:") else "Field"
                        for c in cols
                    ],
                    [[_cell(row.get(c)) for c in cols] for row in r.rows],
                )
            )
        elif r.stages:
            if w.kind == "aging":
                doc.add(
                    Table(
                        w.title,
                        ["Stage", *AGING, "Past target"],
                        [[s.label, *(s.buckets or [0] * 5), s.breaches] for s in r.stages],
                    )
                )
            elif w.kind == "stage_time":
                doc.add(
                    Table(
                        w.title,
                        ["Stage", "Median days", "p75", "p90", "Target"],
                        [
                            [s.label, s.median_days, s.p75_days, s.p90_days, s.target_days]
                            for s in r.stages
                        ],
                    )
                )
            else:
                doc.add(
                    Table(
                        w.title,
                        ["Stage", "Projects", "Conversion"],
                        [
                            [
                                s.label,
                                s.count,
                                f"{round(s.conversion * 100)}%"
                                if s.conversion is not None
                                else None,
                            ]
                            for s in r.stages
                        ],
                    )
                )
        elif r.timeline:
            doc.add(
                Table(
                    w.title,
                    ["Date", "Project", "What"],
                    [[i.date, i.project_name, i.title] for i in r.timeline],
                )
            )
        else:
            doc.add(Callout("Nothing to show here yet.", "info"))
        facts.append({"widget": w.title, "value": r.value, "total": r.total})
    doc.facts = {"dashboard": d.name, "widgets": facts}
    return doc


def _cell(v: Any) -> Any:
    if isinstance(v, dict):
        return v.get("title") or v.get("label")
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return v
