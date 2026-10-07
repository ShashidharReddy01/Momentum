"""Phase 7.5 (spec §6.1): the Excel renderer (openpyxl). A **Summary** sheet (the KPIs as numbers,
paragraphs, small tables and native Excel charts) and one **data sheet** per table that asks for
one (real types, frozen header, autofilter, column widths). Formula-safe: text starting with
``= + - @`` is always written as text, never as a formula. AI paragraphs carry a note."""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from momentum.reports.document import (
    AI_LABEL,
    Callout,
    Cell,
    Chart,
    Heading,
    KPIRow,
    Paragraph,
    ReportDocument,
    Table,
    TaskList,
)

BOLD = Font(bold=True)
HEADER = PatternFill("solid", fgColor="E8EEF7")
AMBER = Font(color="9A6700", italic=True)
FORMULA = ("=", "+", "-", "@")


def _value(v: Cell) -> Any:
    """A real number, date or text (Excel has no time zones)."""
    return v.replace(tzinfo=None) if isinstance(v, datetime) else v


def _put(ws: Worksheet, row: int, col: int, v: Cell) -> None:
    c = ws.cell(row=row, column=col, value=_value(v))
    if isinstance(v, str) and v[:1] in FORMULA:
        c.value = v
        c.data_type = "s"  # text, even though it starts like a formula
    if isinstance(v, date):
        c.number_format = "yyyy-mm-dd"


def _sheet_name(name: str, taken: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", " ", name)[:28] or "Data"
    out, n = base, 2
    while out in taken:
        out, n = f"{base[:25]} {n}", n + 1
    taken.add(out)
    return out


def _data_sheet(wb: Workbook, t: Table, taken: set[str]) -> None:
    ws = wb.create_sheet(_sheet_name(t.sheet or t.title, taken))
    for i, c in enumerate(t.columns, 1):
        cell = ws.cell(row=1, column=i, value=c)
        cell.font, cell.fill = BOLD, HEADER
    for r, row in enumerate(t.rows, 2):
        for i, v in enumerate(row, 1):
            _put(ws, r, i, v)
    ws.freeze_panes = "A2"
    if t.rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(t.columns))}{len(t.rows) + 1}"
    for i, c in enumerate(t.columns, 1):
        longest = max([len(str(c))] + [len(str(r[i - 1] or "")) for r in t.rows[:200]])
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(60, longest + 2))


def render_xlsx(doc: ReportDocument) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Summary"
    taken = {"Summary"}
    ws["A1"] = doc.title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = doc.subtitle
    ws["A3"] = doc.scope_note
    row = 5
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 18
    for b in doc.blocks:
        if isinstance(b, Heading):
            ws.cell(row=row, column=1, value=b.text).font = Font(bold=True, size=12)
            row += 1
        elif isinstance(b, Paragraph):
            c = ws.cell(row=row, column=1, value=b.text)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            if b.ai:
                c.font = AMBER
                ws.cell(row=row, column=6, value=AI_LABEL).font = AMBER
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
            ws.row_dimensions[row].height = max(15, 15 * (len(b.text) // 90 + 1))
            row += 1
        elif isinstance(b, KPIRow):
            for k in b.items:
                ws.cell(row=row, column=1, value=k.label).font = BOLD
                _put(ws, row, 2, k.raw if k.raw is not None else k.value)
                if k.raw is not None and 0 <= k.raw <= 1 and k.value.endswith("%"):
                    ws.cell(row=row, column=2).number_format = "0%"
                if k.delta:
                    ws.cell(row=row, column=3, value=k.delta)
                row += 1
            row += 1
        elif isinstance(b, Table):
            if b.sheet:
                _data_sheet(wb, b, taken)
                ws.cell(
                    row=row,
                    column=1,
                    value=f"{b.title}: see the {b.sheet} sheet ({len(b.rows)} rows)",
                )
                row += 2
                continue
            ws.cell(row=row, column=1, value=b.title).font = BOLD
            row += 1
            for i, c in enumerate(b.columns, 1):
                cell = ws.cell(row=row, column=i, value=c)
                cell.font, cell.fill = BOLD, HEADER
            row += 1
            for r in b.rows:
                for i, v in enumerate(r, 1):
                    _put(ws, row, i, v)
                row += 1
            row += 1
        elif isinstance(b, TaskList):
            ws.cell(row=row, column=1, value=b.title).font = BOLD
            row += 1
            for it in b.items or []:
                _put(ws, row, 1, f"{it.key} {it.title}")
                _put(ws, row, 2, it.due_on)
                _put(ws, row, 3, it.assignee)
                row += 1
            if not b.items:
                ws.cell(row=row, column=1, value=b.empty)
                row += 1
            row += 1
        elif isinstance(b, Callout):
            ws.cell(row=row, column=1, value=b.text).font = Font(italic=True)
            row += 2
        elif isinstance(b, Chart) and b.values:
            # the chart's numbers, then a native chart over them
            first = row
            ws.cell(row=row, column=1, value=b.title).font = BOLD
            for label, v in zip(b.labels, b.values, strict=True):
                row += 1
                _put(ws, row, 1, label)
                _put(ws, row, 2, v)
            chart: BarChart | LineChart | PieChart
            chart = (
                LineChart() if b.kind == "line" else PieChart() if b.kind == "donut" else BarChart()
            )
            chart.title = b.title
            data = Reference(ws, min_col=2, min_row=first + 1, max_row=row)
            cats = Reference(ws, min_col=1, min_row=first + 1, max_row=row)
            chart.add_data(data, titles_from_data=False)
            chart.set_categories(cats)
            if isinstance(chart, BarChart):
                chart.type = "bar"
                chart.legend = None
            chart.height, chart.width = 7, 14
            ws.add_chart(chart, f"E{first}")
            row = max(row + 2, first + 16)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
