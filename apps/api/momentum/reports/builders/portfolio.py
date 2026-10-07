"""Phase 7.5 (spec §6.2): ``portfolio_status`` from the portfolio's own rows (``portfolio_rows_v2``,
as the requester), so the report shows exactly what the portfolio table shows them."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Any

from momentum.domain.fields.models import FieldDef
from momentum.domain.portfolios.lifecycle import effective_columns
from momentum.domain.portfolios.rows import portfolio_rows_v2
from momentum.domain.portfolios.service import get_portfolio
from momentum.reports.builders.common import STATUS_WORDS, BuildContext, day, money, pct, plural
from momentum.reports.document import Callout, Chart, Heading, Kpi, KPIRow, ReportDocument, Table

MONEY = ("currency",)
NUMBER = ("currency", "number")


def value_field(p: Any, fields: list[FieldDef]) -> FieldDef | None:
    """The portfolio's first visible currency column (else number), as the list page uses."""
    by_id = {f.id: f for f in fields}
    cols = effective_columns(p, by_id)
    for types in (MONEY, NUMBER):
        for c in cols:
            if not c["visible"] or not str(c["key"]).startswith("field:"):
                continue
            f = next((x for x in fields if f"field:{x.id}" == c["key"]), None)
            if f is not None and f.type in types:
                return f
    return None


def _unit(f: FieldDef | None) -> str | None:
    o = f.options if f is not None and isinstance(f.options, dict) else None
    return str(o.get("unit")) if o and o.get("unit") else None


async def build_portfolio_status(bc: BuildContext) -> ReportDocument:
    assert bc.spec.scope.portfolio_id is not None
    p = await get_portfolio(bc.session, bc.ctx, bc.spec.scope.portfolio_id)
    result = await portfolio_rows_v2(bc.session, bc.ctx, p, today=bc.today)
    rows = result.rows
    vf = value_field(p, result.fields)
    unit = _unit(vf)

    def val(r: dict[str, Any]) -> float | None:
        v = r["fields"].get(str(vf.id)) if vf else None
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

    start, end = bc.period()
    doc = bc.doc(f"{p.name}: portfolio status", f"{day(start)} to {day(end)}")
    progress = [r["progress"] for r in rows if r["progress"] is not None]
    avg = sum(progress) / len(progress) if progress else None
    at_risk = [r for r in rows if r["status"] in ("at_risk", "off_track")]
    slipping = [r for r in rows if (r["slip_days"] or 0) > 0]
    total = sum(v for r in rows if (v := val(r)) is not None)
    if bc.spec.wants("kpis"):
        items = [
            Kpi("Projects", str(len(rows)), len(rows)),
            Kpi("Average progress", pct(avg), avg),
            Kpi("At risk or off track", str(len(at_risk)), len(at_risk)),
            Kpi("Slipping", str(len(slipping)), len(slipping)),
        ]
        if vf is not None:
            items.append(Kpi(f"Total {vf.name}", money(total, unit), total))
        doc.add(KPIRow(items))
        if result.hidden:
            doc.add(
                Callout(
                    f"{plural(result.hidden, 'project')} in this portfolio you can't see "
                    "aren't counted.",
                    "info",
                )
            )
    doc.narrative_index = len(doc.blocks)
    stage_rows: list[list[Any]] = []
    if bc.spec.wants("stages") and p.stage_field_id is not None:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        labels: dict[str, str] = {}
        for r in rows:
            st = r["stage"] or {}
            key = st.get("option_id") or "none"
            groups[key].append(r)
            labels[key] = st.get("label") or "No stage"
        stage_field = next((f for f in result.fields if f.id == p.stage_field_id), None)
        order = [
            str(o["id"])
            for o in (
                stage_field.options if stage_field and isinstance(stage_field.options, list) else []
            )
            if isinstance(o, dict)
        ]
        targets: dict[str, Any] = p.stage_targets or {}
        for key in [*order, "none"]:
            members = groups.get(key, [])
            if not members:
                continue
            ages = [r["stage_age_days"] for r in members if r["stage_age_days"] is not None]
            target = targets.get(key)
            stage_rows.append(
                [
                    labels.get(key, key),
                    len(members),
                    sum(v for r in members if (v := val(r)) is not None) if vf else None,
                    round(statistics.mean(ages), 1) if ages else None,
                    int(target) if isinstance(target, int | float) else None,
                ]
            )
        doc.add(
            Heading("Stages"),
            Table(
                "Stages",
                [
                    "Stage",
                    "Projects",
                    f"Total {vf.name}" if vf else "Value",
                    "Average days in stage",
                    "Target days",
                ],
                stage_rows,
                sheet="Stages",
            ),
            Chart(
                "Projects per stage",
                "bar",
                [s[0] for s in stage_rows],
                [float(s[1]) for s in stage_rows],
            ),
        )
    if bc.spec.wants("at_risk"):
        doc.add(
            Table(
                "At risk or off track",
                ["Project", "Owner", "Status", "Progress", "Latest update"],
                [
                    [
                        r["name"],
                        r["owner_name"],
                        STATUS_WORDS.get(r["status"] or "", "—"),
                        pct(r["progress"]),
                        (r["latest_update"] or {}).get("title"),
                    ]
                    for r in at_risk
                ],
            )
        )
    windows: list[list[Any]] = []
    if bc.spec.wants("go_lives"):
        for n in (30, 60, 90):
            until = bc.today + timedelta(days=n)
            due = [r for r in rows if r["target_date"] and bc.today <= r["target_date"] <= until]
            windows.append([f"Next {n} days", len(due), ", ".join(r["name"] for r in due[:8])])
        doc.add(Table("Go-lives", ["Window", "Projects", "Which"], windows))
    if bc.spec.wants("slipping"):
        doc.add(
            Table(
                "Slipping",
                ["Project", "Target", "Forecast", "Days late"],
                [
                    [r["name"], r["target_date"], r["forecast_date"], r["slip_days"]]
                    for r in sorted(slipping, key=lambda r: -(r["slip_days"] or 0))
                ],
            )
        )
    # every project, as a data sheet (xlsx) / an appendix table
    doc.add(
        Table(
            "All projects",
            ["Project", "Owner", "Status", "Stage", "Progress", "Overdue", "Target", "Forecast"]
            + ([vf.name] if vf else []),
            [
                [
                    r["name"],
                    r["owner_name"],
                    STATUS_WORDS.get(r["status"] or "", None),
                    (r["stage"] or {}).get("label"),
                    r["progress"],
                    r["overdue"],
                    r["target_date"],
                    r["forecast_date"],
                ]
                + ([val(r)] if vf else [])
                for r in rows
            ],
            sheet="Projects",
        )
    )
    doc.facts = {
        "portfolio": p.name,
        "projects": len(rows),
        "average_progress": pct(avg),
        "at_risk": [r["name"] for r in at_risk],
        "slipping": [{"name": r["name"], "days_late": r["slip_days"]} for r in slipping],
        "total_value": money(total, unit) if vf else None,
        "stages": [
            {"stage": s[0], "projects": s[1], "avg_days": s[3], "target": s[4]} for s in stage_rows
        ],
        "go_lives": [{"window": w[0], "projects": w[1]} for w in windows],
    }
    return doc
