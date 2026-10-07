"""Phase 7.5 (spec §6.1): ``ReportSpec`` → builder (as the requester) → ``ReportDocument`` →
(optional narrative) → renderer. ``outline`` is the preview: the same document without the
narrative or a file, summarised."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.reports.builders.common import BuildContext
from momentum.reports.builders.dashboard import build_dashboard
from momentum.reports.builders.portfolio import build_portfolio_status
from momentum.reports.builders.project import (
    build_closeout,
    build_customer_status,
    build_project_status,
)
from momentum.reports.builders.tasks import build_task_export
from momentum.reports.data import now_utc, today_for
from momentum.reports.document import (
    Chart,
    Heading,
    KPIRow,
    Paragraph,
    ReportDocument,
    Table,
    TaskList,
)
from momentum.reports.narrative import Narrator
from momentum.reports.render.docx import render_docx
from momentum.reports.render.pdf import render_pdf
from momentum.reports.render.text import render_csv, render_md
from momentum.reports.render.xlsx import render_xlsx
from momentum.reports.spec import ReportSpec

BUILDERS: dict[str, Callable[[BuildContext], Awaitable[ReportDocument]]] = {
    "project_status": build_project_status,
    "customer_status": build_customer_status,
    "closeout": build_closeout,
    "portfolio_status": build_portfolio_status,
    "task_export": build_task_export,
    "dashboard": build_dashboard,
}
MIMES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "md": "text/markdown",
    "csv": "text/csv",
}
KIND_WORDS = {
    "project_status": "Status",
    "customer_status": "Customer update",
    "closeout": "Close-out",
    "portfolio_status": "Portfolio status",
    "task_export": "Tasks",
    "dashboard": "Dashboard",
}


@dataclass
class Generated:
    doc: ReportDocument
    data: bytes
    filename: str
    mime: str
    dropped: int  # narrative paragraphs left out because they cited nothing


async def build(session: AsyncSession, ctx: Ctx, spec: ReportSpec) -> ReportDocument:
    now = now_utc()
    bc = BuildContext(session=session, ctx=ctx, spec=spec, today=today_for(ctx), now=now)
    return await BUILDERS[spec.kind](bc)


async def add_narrative(ctx: Ctx, spec: ReportSpec, doc: ReportDocument, narrator: Narrator) -> int:
    """Insert the narrative where the builder said (after the headline numbers). A paragraph
    that cites nothing is dropped; returns how many were."""
    paragraphs = await narrator(ctx, spec.kind, doc.facts)
    kept = [
        Paragraph(text=p.text.strip(), ai=True, cites=p.cites)
        for p in paragraphs
        if p.cites and p.text.strip()
    ]
    if kept:
        at = doc.narrative_index if doc.narrative_index is not None else len(doc.blocks)
        title = "What we learned" if spec.kind == "closeout" else "Summary"
        doc.blocks[at:at] = [Heading(title), *kept]
    return len(paragraphs) - len(kept)


def render(doc: ReportDocument, fmt: str) -> bytes:
    if fmt == "docx":
        return render_docx(doc)
    if fmt == "xlsx":
        return render_xlsx(doc)
    if fmt == "pdf":
        return render_pdf(doc)
    if fmt == "md":
        return render_md(doc)
    return render_csv(doc)


def filename_for(doc: ReportDocument, spec: ReportSpec) -> str:
    base = re.sub(r"[^\w\- ]+", "", doc.title.split(":")[0]).strip() or "Report"
    return f"{base} - {KIND_WORDS[spec.kind]} {doc.generated_at:%Y-%m-%d}.{spec.format}"


async def generate(
    session: AsyncSession, ctx: Ctx, spec: ReportSpec, *, narrator: Narrator | None = None
) -> Generated:
    doc = await build(session, ctx, spec)
    dropped = 0
    if spec.with_narrative and narrator is not None:
        dropped = await add_narrative(ctx, spec, doc, narrator)
    return Generated(
        doc=doc,
        data=render(doc, spec.format),
        filename=filename_for(doc, spec),
        mime=MIMES[spec.format],
        dropped=dropped,
    )


def outline(doc: ReportDocument, spec: ReportSpec) -> dict[str, Any]:
    """The preview: what the file will hold, and about how long it is."""
    items: list[dict[str, Any]] = []
    weight = 0.6  # the title block
    for b in doc.blocks:
        if isinstance(b, Heading):
            items.append({"type": "heading", "title": b.text})
            weight += 0.05
        elif isinstance(b, KPIRow):
            items.append(
                {"type": "kpis", "title": ", ".join(f"{k.label} {k.value}" for k in b.items)}
            )
            weight += 0.1
        elif isinstance(b, Table):
            items.append({"type": "table", "title": b.title, "rows": len(b.rows)})
            weight += 0.08 + len(b.rows) / 38
        elif isinstance(b, TaskList):
            items.append({"type": "tasks", "title": b.title, "rows": len(b.items)})
            weight += 0.05 + len(b.items) / 40
        elif isinstance(b, Chart):
            items.append({"type": "chart", "title": b.title})
            weight += 0.35
        elif isinstance(b, Paragraph):
            weight += len(b.text) / 3000
    if spec.with_narrative:
        items.insert(
            min(doc.narrative_index or len(items), len(items)),
            {"type": "narrative", "title": "AI-drafted summary (marked, review before sending)"},
        )
        weight += 0.3
    sheets = 1 + sum(1 for b in doc.blocks if isinstance(b, Table) and b.sheet)
    return {
        "title": doc.title,
        "subtitle": doc.subtitle,
        "scope_note": doc.scope_note,
        "items": items,
        "pages": max(1, round(weight)) if spec.format in ("docx", "pdf") else None,
        "sheets": sheets if spec.format == "xlsx" else None,
    }
