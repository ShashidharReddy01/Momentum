"""Phase 7.5 (spec §6.1): the PDF renderer (reportlab platypus). DejaVu Sans for Unicode, A4 or
Letter, a header and a footer with page numbers, tables whose header repeats, charts drawn as
vector graphics, and every AI paragraph behind an amber left rule with "AI-drafted, review
before sending"."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)
from reportlab.platypus import (
    PageBreak as RLPageBreak,
)
from reportlab.platypus import (
    Paragraph as RLParagraph,
)
from reportlab.platypus import (
    Table as RLTable,
)
from reportlab.platypus.flowables import Flowable

from momentum.reports.document import (
    AI_LABEL,
    Callout,
    Chart,
    Heading,
    KPIRow,
    PageBreak,
    Paragraph,
    ReportDocument,
    Table,
    TaskList,
)
from momentum.reports.render.text import text_of

FONTS = Path(__file__).resolve().parent.parent / "fonts"
AMBER = colors.HexColor("#C98500")
INK = colors.HexColor("#1E2228")
MUTED = colors.HexColor("#6E747E")
CHART = colors.HexColor("#2A78D6")
TONES = {
    "info": colors.HexColor("#2A78D6"),
    "warn": AMBER,
    "crit": colors.HexColor("#E34948"),
    "ok": colors.HexColor("#1BAF7A"),
}
_registered = False


def _fonts() -> None:
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONTS / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONTS / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")
    _registered = True


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("body", fontName="DejaVu", fontSize=9.5, leading=13, textColor=INK)
    return {
        "body": base,
        "title": ParagraphStyle(
            "title", parent=base, fontName="DejaVu-Bold", fontSize=18, leading=22
        ),
        "sub": ParagraphStyle("sub", parent=base, textColor=MUTED, fontSize=9),
        "h1": ParagraphStyle(
            "h1",
            parent=base,
            fontName="DejaVu-Bold",
            fontSize=13,
            leading=17,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base,
            fontName="DejaVu-Bold",
            fontSize=11,
            leading=15,
            spaceBefore=8,
            spaceAfter=3,
        ),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.5, leading=11),
        "label": ParagraphStyle(
            "label", parent=base, fontName="DejaVu-Bold", fontSize=7.5, textColor=AMBER
        ),
        "kpi": ParagraphStyle("kpi", parent=base, fontName="DejaVu-Bold", fontSize=15, leading=18),
        "kpil": ParagraphStyle("kpil", parent=base, fontSize=7.5, textColor=MUTED),
    }


def _ruled(inner: list[Flowable], color: Any, width: float) -> RLTable:
    """Content behind a coloured left rule (AI paragraphs, callouts)."""
    t = RLTable([[x] for x in inner], colWidths=[width - 8])
    t.setStyle(
        TableStyle(
            [
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, color),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return t


def _chart(b: Chart, width: float) -> Drawing:
    if b.kind == "line":
        d = Drawing(width, 150)
        lp = LinePlot()
        lp.x, lp.y, lp.width, lp.height = 40, 20, width - 60, 110
        lp.data = [[(i, v) for i, v in enumerate(b.values)]]
        lp.lines[0].strokeColor = CHART
        lp.lines[0].strokeWidth = 2
        lp.xValueAxis.labels.fontName = lp.yValueAxis.labels.fontName = "DejaVu"
        lp.xValueAxis.labels.fontSize = lp.yValueAxis.labels.fontSize = 7
        d.add(lp)
        return d
    n = max(1, len(b.values))
    height = 18 * n + 30
    d = Drawing(width, height)
    bc = HorizontalBarChart()
    bc.x, bc.y, bc.width, bc.height = 130, 10, width - 180, height - 20
    bc.data = [list(reversed(b.values))]
    bc.categoryAxis.categoryNames = [label[:24] for label in reversed(b.labels)]
    bc.categoryAxis.labels.fontName = bc.valueAxis.labels.fontName = "DejaVu"
    bc.categoryAxis.labels.fontSize = bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.valueMin = 0
    bc.bars[0].fillColor = CHART
    bc.barLabelFormat = "%.0f"
    bc.barLabels.fontName = "DejaVu"
    bc.barLabels.fontSize = 7
    bc.barLabels.nudge = 8
    d.add(bc)
    return d


def render_pdf(doc: ReportDocument, *, letter: bool = False) -> bytes:
    _fonts()
    st = _styles()
    size = LETTER if letter else A4
    buf = io.BytesIO()
    frame_w = size[0] - 36 * mm

    def p(text: str, style: str = "body") -> RLParagraph:
        return RLParagraph(escape(text), st[style])

    story: list[Flowable] = [
        p(doc.title, "title"),
        p(doc.subtitle, "sub"),
        p(doc.scope_note, "sub"),
        Spacer(1, 8),
    ]
    for b in doc.blocks:
        if isinstance(b, Heading):
            story.append(p(b.text, "h1" if b.level <= 1 else "h2"))
        elif isinstance(b, Paragraph):
            if b.ai:
                story.append(_ruled([p(AI_LABEL, "label"), p(b.text)], AMBER, frame_w))
            else:
                story.append(p(b.text))
            story.append(Spacer(1, 4))
        elif isinstance(b, KPIRow):
            cells = [
                [p(k.value, "kpi") for k in b.items],
                [p(k.label + (f" ({k.delta})" if k.delta else ""), "kpil") for k in b.items],
            ]
            t = RLTable(cells, colWidths=[frame_w / max(1, len(b.items))] * len(b.items))
            t.setStyle(
                TableStyle(
                    [("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 1), (-1, 1), 8)]
                )
            )
            story.append(t)
        elif isinstance(b, Table):
            story.append(p(b.title, "h2"))
            if not b.rows:
                story.append(p("Nothing here."))
                continue
            data = [[p(c, "cell") for c in b.columns]] + [
                [p(text_of(v), "cell") for v in r] for r in b.rows
            ]
            t = RLTable(data, repeatRows=1, colWidths=[frame_w / len(b.columns)] * len(b.columns))
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9DDE3")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(t)
        elif isinstance(b, TaskList):
            story.append(p(b.title, "h2"))
            if not b.items:
                story.append(p(b.empty))
            for it in b.items:
                bits = [
                    x for x in (it.assignee, f"due {it.due_on:%d %b}" if it.due_on else None) if x
                ]
                story.append(
                    p(
                        f"{'✓ ' if it.done else '• '}{it.key} {it.title}"
                        + (f" ({', '.join(bits)})" if bits else "")
                    )
                )
        elif isinstance(b, Callout):
            story.append(_ruled([p(b.text)], TONES[b.tone], frame_w))
            story.append(Spacer(1, 4))
        elif isinstance(b, Chart) and b.values:
            story.append(KeepTogether([p(b.title, "h2"), _chart(b, frame_w)]))
        elif isinstance(b, PageBreak):
            story.append(RLPageBreak())

    def decorate(canvas: Any, d: Any) -> None:
        canvas.saveState()
        canvas.setFont("DejaVu", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, size[1] - 12 * mm, doc.title[:90])
        canvas.drawString(18 * mm, 10 * mm, f"Momentum · {doc.generated_at:%d %b %Y}")
        canvas.drawRightString(size[0] - 18 * mm, 10 * mm, f"Page {d.page}")
        canvas.restoreState()

    template = SimpleDocTemplate(
        buf,
        pagesize=size,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=doc.title,
        author="Momentum",
    )
    template.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buf.getvalue()
