"""Reading a document's pages (spec §9.3.6, ADR-0014), in the COAP notebook's order: the PDF's
own text layer first; for a page whose text is empty or poor, OCR (Tesseract, when the server has
it); only a page still poor after OCR goes to the model as an image (vision). Every page keeps its
words with positions (PDF points, top-left origin; pixels for an image), which is what provenance
boxes and the "printed on its own row" check use.

The text-confidence heuristic is the notebook's (`compute_text_confidence`, with its widened safe
punctuation): density x share of clean characters, per page."""

from __future__ import annotations

import io
from typing import Any

from pydantic import BaseModel

TEXT_FLOOR = 0.75  # the notebook's VISION_CONFIDENCE_FLOOR
_SAFE = set(".,:;()/%$€£¥&'\"-+#@")

Word = tuple[str, float, float, float, float]  # text, x0, top, x1, bottom


class Page(BaseModel):
    n: int
    width: float
    height: float
    text: str
    words: list[Word]
    source: str  # text | ocr | vision
    confidence: float


class Reading(BaseModel):
    pages: list[Page]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages if p.source != "vision")

    @property
    def vision_pages(self) -> list[int]:
        return [p.n for p in self.pages if p.source == "vision"]

    @property
    def ocr_pages(self) -> list[int]:
        return [p.n for p in self.pages if p.source == "ocr"]

    @property
    def text_pages(self) -> list[int]:
        return [p.n for p in self.pages if p.source == "text"]

    @property
    def confidence(self) -> float:
        usable = [p.confidence for p in self.pages if p.source != "vision"]
        return round(sum(usable) / len(usable), 4) if usable else 0.0


def text_confidence(text: str, page_count: int = 1) -> float:
    if not text.strip() or page_count <= 0:
        return 0.0
    density = min(1.0, len(text) / (500 * page_count))
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    clean = sum(1 for c in chars if c.isalnum() or c in _SAFE) / len(chars)
    return round(density * clean, 4)


def clean_ratio(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if c.isalnum() or c in _SAFE) / len(chars)


def good_text(text: str) -> bool:
    """Whether a page's text can be trusted as is: some real text (80+ characters) that is
    mostly clean characters. Unlike the notebook's density score, a short but clean digital
    invoice page counts as good (density alone sent those to vision)."""
    return len(text.strip()) >= 80 and clean_ratio(text) >= 0.85


def _pdf_pages(data: bytes) -> list[tuple[str, list[Word], float, float]]:
    import pdfplumber

    out: list[tuple[str, list[Word], float, float]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for p in pdf.pages:
            text = p.extract_text() or ""
            words = [
                (
                    str(w["text"]),
                    round(float(w["x0"]), 1),
                    round(float(w["top"]), 1),
                    round(float(w["x1"]), 1),
                    round(float(w["bottom"]), 1),
                )
                for w in p.extract_words(keep_blank_chars=False, x_tolerance=1.5, y_tolerance=2)
            ]
            out.append((text, words, float(p.width), float(p.height)))
    return out


def _ocr_words(page: Any, scale: float) -> list[Word]:
    return [
        (
            w.text,
            round(w.x0 / scale, 1),
            round(w.top / scale, 1),
            round(w.x1 / scale, 1),
            round(w.bottom / scale, 1),
        )
        for w in page.words
    ]


def read_pdf(job: Any, data: bytes, *, use_ocr: bool) -> Reading:
    """Every page of a PDF, text → OCR → vision. Runs inside a step (OCR is local CPU work)."""
    pages: list[Page] = []
    can_ocr = use_ocr and bool(job.ocr_available)
    for n, (text, words, width, height) in enumerate(_pdf_pages(data), start=1):
        conf = text_confidence(text)
        if good_text(text):
            pages.append(
                Page(
                    n=n,
                    width=width,
                    height=height,
                    text=text,
                    words=words,
                    source="text",
                    confidence=conf,
                )
            )
            continue
        if can_ocr:
            png, scale = job.render_page_for_ocr(data, n)
            o = job.ocr(png)
            oconf = text_confidence(o.text)
            if good_text(o.text) and o.mean_conf >= 70:
                pages.append(
                    Page(
                        n=n,
                        width=width,
                        height=height,
                        text=o.text,
                        words=_ocr_words(o, scale),
                        source="ocr",
                        confidence=oconf,
                    )
                )
                continue
        pages.append(
            Page(
                n=n,
                width=width,
                height=height,
                text=text,
                words=words,
                source="vision",
                confidence=conf,
            )
        )
    return Reading(pages=pages)


def read_image(job: Any, data: bytes, *, use_ocr: bool) -> Reading:
    """A photo or scan of one page: OCR when possible, else vision."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        width, height = im.size
    if use_ocr and job.ocr_available:
        o = job.ocr(data)
        conf = text_confidence(o.text)
        if good_text(o.text) and o.mean_conf >= 70:
            return Reading(
                pages=[
                    Page(
                        n=1,
                        width=width,
                        height=height,
                        text=o.text,
                        words=_ocr_words(o, 1.0),
                        source="ocr",
                        confidence=conf,
                    )
                ]
            )
    return Reading(
        pages=[
            Page(
                n=1, width=width, height=height, text="", words=[], source="vision", confidence=0.0
            )
        ]
    )
