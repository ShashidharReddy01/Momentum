"""Phase 7.6 S76-04 (spec §6.6): ``records_export``: every record of one type in a project or a
portfolio the requester can see (exports need editor: the report lives with the project or
portfolio, which ``home_of`` checks). A **Records** sheet with the type's columns, money as numbers
with the currency beside them, and one sheet per list (``lines``) with a row per item. Text that
looks like a formula stays text (the renderers' rule)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from momentum.domain.access import get_visible_project
from momentum.domain.dashboards.query_scope import scope_projects
from momentum.domain.records import paths
from momentum.domain.records.models import Record
from momentum.domain.records.query import type_display
from momentum.domain.records.service import visible
from momentum.reports.builders.common import BuildContext, day
from momentum.reports.document import Cell, Heading, Kpi, KPIRow, ReportDocument, Table

MAX_ROWS = 20_000


def _header(path: str) -> str:
    return path.replace("[]", "").replace("_", " ").replace(".", " ").strip().capitalize()


def _cell(value: Any, money: bool, is_date: bool) -> Cell:
    if value is None:
        return None
    if money:
        try:
            return float(Decimal(str(value)))
        except InvalidOperation:
            return str(value)
    if is_date:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return str(value)
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, dict | list):
        return None
    return str(value)


async def build_records_export(bc: BuildContext) -> ReportDocument:
    spec = bc.spec
    assert spec.record_type is not None
    s = spec.scope
    if s.project_id is not None:
        project, _ = await get_visible_project(bc.session, bc.ctx, s.project_id)
        project_ids, where = [project.id], project.name
    else:
        assert s.portfolio_id is not None
        scope = await scope_projects(bc.session, bc.ctx, portfolio_id=s.portfolio_id)
        project_ids = [p.id for p in scope.projects]
        where = scope.portfolio.name if scope.portfolio else "Portfolio"
    row = await type_display(bc.session, bc.ctx, spec.record_type)
    display = row.display
    stmt = select(Record).where(
        await visible(bc.session, bc.ctx),
        Record.type == spec.record_type,
        Record.project_id.in_(project_ids),
    )
    if spec.record_status:
        stmt = stmt.where(Record.status.in_(spec.record_status))
    else:
        stmt = stmt.where(Record.status.not_in(("void", "superseded")))
    if spec.period is not None:
        stmt = stmt.where(Record.occurred_on.between(spec.period.start, spec.period.end))
    records = list(
        (
            await bc.session.execute(
                stmt.order_by(Record.occurred_on.nulls_last(), Record.created_at).limit(MAX_ROWS)
            )
        ).scalars()
    )
    money = set(display.get("money") or [])
    dates = set(display.get("dates") or [])
    currency_field = display.get("currency_field")
    columns = [c for c in display.get("columns") or [] if "[" not in c] or ["title"]
    doc = bc.doc(f"{where}: {row.label} records", f"Exported {day(bc.today)}")
    head = ["Title", "Status", *[_header(c) for c in columns if c != currency_field]]
    if currency_field:
        head.append("Currency")
    rows: list[list[Cell]] = []
    for r in records:
        line: list[Cell] = [r.title, r.status]
        for c in columns:
            if c == currency_field:
                continue
            line.append(_cell(paths.get(r.data, c), c in money, c in dates))
        if currency_field:
            line.append(r.currency)
        rows.append(line)
    totals: dict[str, Decimal] = {}
    for r in records:
        if r.amount is not None:
            totals[r.currency or "?"] = totals.get(r.currency or "?", Decimal(0)) + r.amount
    doc.add(
        KPIRow(
            [
                Kpi("Records", str(len(records)), len(records)),
                *[Kpi(f"Total {cur}", f"{amt:,.2f}", float(amt)) for cur, amt in totals.items()],
            ]
        ),
        Heading(row.label, 2),
        Table(f"{row.label} records", head, rows, sheet="Records"),
    )
    for array, label in (display.get("arrays") or {}).items():
        prefix = f"{array}[]."
        item_paths = sorted({p[len(prefix) :] for p in money | dates if p.startswith(prefix)})
        keys: list[str] = []
        for r in records:
            for item in r.data.get(array) or []:
                if isinstance(item, dict):
                    keys += [
                        k for k in item if k not in keys and not isinstance(item[k], dict | list)
                    ]
        keys += [k for k in item_paths if k not in keys]  # first-seen order, then the rest
        lines: list[list[Cell]] = []
        for r in records:
            for i, item in enumerate(r.data.get(array) or [], start=1):
                if not isinstance(item, dict):
                    continue
                lines.append(
                    [
                        r.title,
                        i,
                        *[
                            _cell(item.get(k), f"{prefix}{k}" in money, f"{prefix}{k}" in dates)
                            for k in keys
                        ],
                        *([r.currency] if currency_field else []),
                    ]
                )
        doc.add(
            Table(
                str(label),
                [
                    "Record",
                    "#",
                    *[_header(k) for k in keys],
                    *(["Currency"] if currency_field else []),
                ],
                lines,
                sheet=str(label)[:31],
            )
        )
    return doc
