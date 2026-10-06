"""PDF: pdfplumber for each page's text and tables, pypdf for encryption and page count.

A page with fewer than 30 characters of text and a picture covering more than half of it is a
**scanned page**: it becomes an image reference Mo can look at (vision, on request). JavaScript,
forms, links and attachments inside the PDF are never run or followed.
"""

from __future__ import annotations

import io

from momentum.files.model import ParseResult
from momentum.files.parsers.base import Builder
from momentum.files.safety import EncryptedFile

SCANNED_MAX_CHARS = 30
SCANNED_MIN_IMAGE_SHARE = 0.5


def parse_pdf(data: bytes, filename: str, mime: str) -> ParseResult:
    import pdfplumber
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        # an owner-password-only PDF opens with an empty user password: readable
        try:
            if not reader.decrypt(""):
                raise EncryptedFile("The PDF is password-protected")
        except Exception as e:
            raise EncryptedFile("The PDF is password-protected") from e
    b = Builder(data, filename, mime, "pdf")
    with pdfplumber.open(io.BytesIO(data), password="") as pdf:
        b.header.pages = len(pdf.pages)
        scanned = 0
        for n, page in enumerate(pdf.pages, start=1):
            loc = f"p{n}"
            text = page.extract_text() or ""
            area = float(page.width * page.height) or 1.0
            images = page.images
            covered = sum(
                abs(float(i["x1"]) - float(i["x0"])) * abs(float(i["bottom"]) - float(i["top"]))
                for i in images
            )
            if len(text.strip()) < SCANNED_MAX_CHARS and covered / area > SCANNED_MIN_IMAGE_SHARE:
                scanned += 1
                b.image(loc, page=n, scanned=True, width=int(page.width), height=int(page.height))
                continue
            b.text(text, loc)
            for t, table in enumerate(page.extract_tables() or [], start=1):
                b.table([[c or "" for c in row] for row in table], f"{loc} table {t}")
            for i in images:
                b.image(
                    loc,
                    page=n,
                    width=int(float(i["x1"]) - float(i["x0"])),
                    height=int(float(i["bottom"]) - float(i["top"])),
                )
        if scanned:
            b.warn(
                f"{scanned} page{'s' if scanned > 1 else ''} look scanned (no text layer): Mo can "
                "read them by looking at the page"
            )
    return b.done()
