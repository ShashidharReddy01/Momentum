"""Phase 7.6 S76-09 (ADR-0014): OCR of a page image with Tesseract, when the server has it. Local
by design: OCR is what first produces the text, so nothing leaves the process. Words come back
with their positions, so OCR'd pages get provenance boxes like text pages do.

`available()` is false when OCR is turned off (`MOMENTUM_OCR_ENABLED`) or the Tesseract binary
isn't installed; callers then go straight to vision, so a missing binary never breaks a job."""

from __future__ import annotations

import io
import shutil
from dataclasses import dataclass
from functools import cache

from momentum.core.settings import Settings


@dataclass(frozen=True)
class OcrWord:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    conf: float  # 0-100, Tesseract's own


@dataclass(frozen=True)
class OcrPage:
    text: str
    words: list[OcrWord]
    width: int
    height: int
    mean_conf: float


@cache
def _binary(cmd: str | None) -> str | None:
    if cmd:
        return cmd if shutil.which(cmd) or _exists(cmd) else None
    return shutil.which("tesseract")


def _exists(path: str) -> bool:
    from pathlib import Path

    return Path(path).is_file()


def available(settings: Settings) -> bool:
    return settings.ocr_enabled and _binary(settings.tesseract_cmd) is not None


def ocr_image(settings: Settings, image: bytes) -> OcrPage:
    """Text and words (pixel coordinates of this image) of one page image."""
    import pytesseract
    from PIL import Image

    binary = _binary(settings.tesseract_cmd)
    if not settings.ocr_enabled or binary is None:
        raise RuntimeError("OCR isn't available on this server")
    pytesseract.pytesseract.tesseract_cmd = binary
    with Image.open(io.BytesIO(image)) as img:
        img.load()
        data = pytesseract.image_to_data(
            img,
            lang=settings.ocr_languages,
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )
        width, height = img.size
    words: list[OcrWord] = []
    lines: dict[tuple[int, int, int], list[str]] = {}
    for i, raw in enumerate(data["text"]):
        text = str(raw).strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        left, top, w, h = (int(data[k][i]) for k in ("left", "top", "width", "height"))
        words.append(OcrWord(text, left, top, left + w, top + h, conf))
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        lines.setdefault(key, []).append(text)
    text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
    mean = sum(w.conf for w in words) / len(words) if words else 0.0
    return OcrPage(text=text, words=words, width=width, height=height, mean_conf=round(mean, 1))
