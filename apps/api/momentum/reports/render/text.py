"""Phase 7.5 (spec §6.1): the Markdown and CSV renderers.

Markdown marks every AI paragraph ``> AI-drafted: …``. CSV is one table (the task table of an
export, else the document's first table), with the S7.4 cell rules: a cell that a spreadsheet
would run as a formula is prefixed (``safe_cell``).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from momentum.domain.tasks.csv_export import safe_cell
from momentum.reports.document import (
    AI_LABEL,
    Callout,
    Cell,
    Chart,
    Heading,
    KPIRow,
    PageBreak,
    Paragraph,
    ReportDocument,
    Table,
    TaskList,
)


def text_of(v: Cell) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if not v.is_integer() else f"{int(v):,}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _md_cell(v: Cell) -> str:
    return text_of(v).replace("|", "\\|").replace("\n", " ")


def render_md(doc: ReportDocument) -> bytes:
    out = [f"# {doc.title}", "", f"_{doc.subtitle}_", "", f"_{doc.scope_note}_", ""]
    for b in doc.blocks:
        if isinstance(b, Heading):
            out += [f"{'#' * min(6, b.level + 1)} {b.text}", ""]
        elif isinstance(b, Paragraph):
            out += [f"> AI-drafted: {b.text}" if b.ai else b.text, ""]
        elif isinstance(b, KPIRow):
            out += [" · ".join(f"**{k.label}:** {k.value}" for k in b.items), ""]
        elif isinstance(b, Table):
            out += [f"**{b.title}**", ""]
            if not b.rows:
                out += ["Nothing here.", ""]
                continue
            out.append("| " + " | ".join(_md_cell(c) for c in b.columns) + " |")
            out.append("|" + "---|" * len(b.columns))
            for r in b.rows:
                out.append("| " + " | ".join(_md_cell(c) for c in r) + " |")
            out.append("")
        elif isinstance(b, TaskList):
            out += [f"**{b.title}**", ""]
            if not b.items:
                out += [b.empty, ""]
                continue
            for t in b.items:
                bits = [
                    x
                    for x in (t.assignee, f"due {t.due_on.isoformat()}" if t.due_on else None)
                    if x
                ]
                mark = "x" if t.done else " "
                out.append(
                    f"- [{mark}] {t.key} {t.title}" + (f" ({', '.join(bits)})" if bits else "")
                )
            out.append("")
        elif isinstance(b, Callout):
            out += [f"> **{b.tone.upper() if b.tone != 'info' else 'Note'}:** {b.text}", ""]
        elif isinstance(b, Chart):
            out += [f"**{b.title}**", ""]
            out += [f"- {label}: {text_of(v)}" for label, v in zip(b.labels, b.values, strict=True)]
            out.append("")
        elif isinstance(b, PageBreak):
            out += ["---", ""]
    if doc.ai_paragraphs:
        out += ["", f"_Paragraphs marked AI-drafted: {AI_LABEL}._"]
    return ("\n".join(out).rstrip() + "\n").encode("utf-8")


def render_csv(doc: ReportDocument) -> bytes:
    tables = [b for b in doc.blocks if isinstance(b, Table)]
    table = next((t for t in tables if t.sheet == "Tasks"), tables[0] if tables else None)
    buf = io.StringIO()
    w = csv.writer(buf)
    if table is not None:
        w.writerow([safe_cell(c) for c in table.columns])
        for r in table.rows:
            w.writerow([safe_cell(text_of(c)) for c in r])
    # BOM: Excel opens UTF-8 (accents, CJK) correctly
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
