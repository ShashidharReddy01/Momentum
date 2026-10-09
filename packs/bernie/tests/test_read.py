"""Reading (spec §9.3.6, ADR-0014): text first, OCR for a scan (when Tesseract is installed),
vision only when neither gives good text; OCR'd words keep page positions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from momentum_pack_bernie import read
from synth import build as B

S = B.specs()

_WINDOWS = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
TESSERACT = shutil.which("tesseract") or (str(_WINDOWS) if _WINDOWS.is_file() else None)


class NoOcr:
    ocr_available = False


class RealOcr:
    """The job's OCR helpers, backed by the real core module and the local Tesseract."""

    def __init__(self) -> None:
        from momentum.core.settings import Settings

        self.settings = Settings(
            tesseract_cmd=TESSERACT, database_url="postgresql+psycopg://x:y@localhost/z"
        )

    @property
    def ocr_available(self) -> bool:
        from momentum.files import ocr

        return ocr.available(self.settings)

    def ocr(self, image: bytes) -> Any:
        from momentum.files import ocr

        return ocr.ocr_image(self.settings, image)

    def render_page_for_ocr(self, data: bytes, page: int) -> tuple[bytes, float]:
        from momentum.files import render

        return render.render_pdf_page_for_ocr(data, page)


def test_text_pages_keep_their_words_with_positions() -> None:
    r = read.read_pdf(NoOcr(), B.pdf(S["northwind_simple"]), use_ocr=False)
    [p] = r.pages
    assert p.source == "text" and p.width == pytest.approx(595.3, abs=1)
    word = next(w for w in p.words if w[0] == "NW-2041")
    assert word[1] > 300  # printed on the right
    assert r.text_pages == [1] and r.vision_pages == []


def test_a_scan_without_ocr_goes_to_vision() -> None:
    r = read.read_pdf(NoOcr(), B.pdf(S["woodgrove_scan"]), use_ocr=False)
    assert r.vision_pages == [1]


def test_a_short_clean_page_is_good_text() -> None:
    assert read.good_text(
        "INVOICE NW-2041 Northwind Data Ltd 12 Fleet Street London total 1,000.00 GBP thank you"
    )
    assert not read.good_text(
        "§§ ¶¶ ¤¤ ∑∑ ≈≈ ◊◊ ¬¬ ∂∂ ∆∆ ¥¥ ©© ®® ¶¶ §§ ¤¤ ∑∑ ≈≈ ◊◊ ¬¬ ∂∂ ∆∆ ©© ®® ¶¶ §§ ¤¤ ∑∑ ≈≈ ◊◊"
    )
    assert not read.good_text("short")


@pytest.mark.skipif(TESSERACT is None, reason="Tesseract isn't installed here")
def test_a_scan_is_ocrd_with_positions() -> None:
    r = read.read_pdf(RealOcr(), B.pdf(S["woodgrove_scan"]), use_ocr=True)
    [p] = r.pages
    assert p.source == "ocr" and "INV-0041" in p.text and "1,250.00" in p.text
    box = next(w for w in p.words if w[0] == "INV-0041")
    assert 0 < box[1] < p.width and 0 < box[2] < 200  # page points, near the top
