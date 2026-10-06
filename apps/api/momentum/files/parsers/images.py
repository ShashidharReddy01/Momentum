"""Images: one image reference with its size (Pillow, header only). The pixels are read only when
a person asks Mo to look (``files/render.py``, EXIF stripped)."""

from __future__ import annotations

from momentum.files.model import ParseResult
from momentum.files.parsers.base import Builder
from momentum.files.safety import check_image_header


def parse_image(data: bytes, filename: str, mime: str) -> ParseResult:
    b = Builder(data, filename, mime, "image")
    w, h = check_image_header(data)
    b.image("image", width=w, height=h, alt=filename)
    return b.done()
