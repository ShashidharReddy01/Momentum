"""Phase 7.5: simple chart pictures for Word documents (Pillow; the PDF draws its charts as
vector graphics instead). Bars and lines in the first chart colour, labels in DejaVu Sans."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from momentum.reports.document import Chart

FONT = Path(__file__).resolve().parent.parent / "fonts" / "DejaVuSans.ttf"
INK = (30, 34, 40)
MUTED = (110, 116, 126)
BAR = (42, 120, 214)  # --chart-1
PALETTE = [
    (42, 120, 214),
    (235, 104, 52),
    (27, 175, 122),
    (237, 161, 0),
    (232, 123, 164),
    (0, 131, 0),
    (74, 58, 167),
    (227, 73, 72),
]


def render_png(chart: Chart, width: int = 1200, row: int = 44) -> bytes:
    font = ImageFont.truetype(str(FONT), 22)
    small = ImageFont.truetype(str(FONT), 18)
    n = max(1, len(chart.values))
    height = 420 if chart.kind == "line" else 40 + row * n
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    top = max(chart.values, default=0) or 1
    if chart.kind == "line":
        left, right, y0, y1 = 80, width - 30, 30, height - 60
        pts = []
        for i, v in enumerate(chart.values):
            x = left + (right - left) * (i / max(1, n - 1))
            y = y1 - (y1 - y0) * (v / top)
            pts.append((x, y))
        d.line([(left, y1), (right, y1)], fill=MUTED, width=2)
        if len(pts) > 1:
            d.line(pts, fill=BAR, width=4)
        for x, y in pts:
            d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=BAR)
        for i in (0, n - 1):
            if chart.labels:
                d.text((pts[i][0] - 40, y1 + 12), chart.labels[i][:12], fill=MUTED, font=small)
        d.text((10, y0 - 10), f"{top:,.0f}", fill=MUTED, font=small)
    else:
        label_w = 360
        for i, (label, v) in enumerate(zip(chart.labels, chart.values, strict=True)):
            y = 20 + i * row
            d.text((10, y + 6), label[:28], fill=INK, font=font)
            w = int((width - label_w - 140) * (v / top))
            colour = PALETTE[i % len(PALETTE)] if chart.kind == "donut" else BAR
            d.rectangle([label_w, y + 4, label_w + max(2, w), y + row - 10], fill=colour)
            d.text(
                (label_w + max(2, w) + 10, y + 6),
                f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}",
                fill=INK,
                font=font,
            )
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
