"""Word: .docx/.docm (python-docx), .rtf (striprtf), .doc (not read: says how to fix).

Body paragraphs and tables in document order; headings build the outline and give every block a
section locator (``§ Scope > Out of scope``); tables are ``table N``; headers, footers, comments
and footnotes are their own blocks; inline pictures are image references; a .docm's macros are
read as text.
"""

from __future__ import annotations

import io
import re
import zipfile

from momentum.files.macros import read_macros
from momentum.files.model import ParseResult
from momentum.files.parsers.base import Builder, section_locator, unsupported

EMU_PER_PX = 9525
_HEADING = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _level(style: str | None) -> int | None:
    if not style:
        return None
    if style.lower() == "title":
        return 1
    m = _HEADING.match(style)
    return int(m.group(1)) if m else None


_MACRO_MAIN = b"application/vnd.ms-word.document.macroEnabled.main+xml"
_TEMPLATE_MAIN = b"application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
_DOCX_MAIN = b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def _readable_copy(data: bytes) -> bytes:
    """python-docx opens only plain .docx: a .docm or .dotx gets the plain main-part content type
    in an in-memory copy (the original bytes still go to the macro reader)."""
    with zipfile.ZipFile(io.BytesIO(data)) as src:
        types = src.read("[Content_Types].xml")
        if _MACRO_MAIN not in types and _TEMPLATE_MAIN not in types:
            return data
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for info in src.infolist():
                part = src.read(info.filename)
                if info.filename == "[Content_Types].xml":
                    part = part.replace(_MACRO_MAIN, _DOCX_MAIN).replace(_TEMPLATE_MAIN, _DOCX_MAIN)
                z.writestr(info, part)
    return out.getvalue()


def parse_docx(data: bytes, filename: str, mime: str) -> ParseResult:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    b = Builder(data, filename, mime, "document")
    doc = Document(io.BytesIO(_readable_copy(data)))
    path: list[str] = []
    tables = 0
    for item in doc.iter_inner_content():
        if isinstance(item, Paragraph):
            style = item.style.name if item.style is not None else None
            level = _level(style)
            text = item.text
            if level is not None and text.strip():
                path = [*path[: level - 1], text.strip()]
                b.heading(text, level, section_locator(path))
                continue
            b.text(text, section_locator(path), style=style)
        elif isinstance(item, Table):
            tables += 1
            rows = [[cell.text for cell in row.cells] for row in item.rows]
            b.table(rows, f"table {tables}", title=" > ".join(path) or None)
    for i, section in enumerate(doc.sections, start=1):
        for where, part in (("header", section.header), ("footer", section.footer)):
            if part.is_linked_to_previous and i > 1:
                continue
            b.text("\n".join(p.text for p in part.paragraphs), f"{where} (section {i})")
    try:
        for c in doc.comments:
            who = c.author or "someone"
            b.text(f"{who}: {c.text}", f"comment {c.comment_id}", style="comment")
    except (AttributeError, KeyError):
        pass  # no comments part
    _footnotes(doc, b)
    for n, shape in enumerate(doc.inline_shapes, start=1):
        try:
            w, h = int(shape.width) // EMU_PER_PX, int(shape.height) // EMU_PER_PX
        except (TypeError, ValueError):
            w = h = 0
        b.image(f"image {n}", width=w or None, height=h or None)
    if filename.lower().endswith((".docm", ".dotm")) or "macroenabled" in mime.lower():
        b.model.macros = read_macros(data, filename)
    return b.done()


def _footnotes(doc: object, b: Builder) -> None:
    from docx.oxml.parser import parse_xml

    package = doc.part.package  # type: ignore[attr-defined]
    for part in package.iter_parts():
        if str(part.partname) != "/word/footnotes.xml":
            continue
        root = parse_xml(part.blob)
        for fn in root.iter(f"{_W}footnote"):
            fid = fn.get(f"{_W}id")
            if fid is None or int(fid) < 1:  # separators
                continue
            text = "".join(t.text or "" for t in fn.iter(f"{_W}t"))
            b.text(text, f"footnote {fid}", style="footnote")


def parse_rtf(data: bytes, filename: str, mime: str) -> ParseResult:
    from striprtf.striprtf import rtf_to_text

    b = Builder(data, filename, mime, "document")
    text: str = rtf_to_text(data.decode("latin-1", errors="replace"), errors="ignore")  # type: ignore[no-untyped-call]
    for i, para in enumerate(p for p in text.split("\n\n") if p.strip()):
        b.text(para, f"paragraph {i + 1}")
    return b.done()


def parse_doc(data: bytes, filename: str, mime: str) -> ParseResult:
    return unsupported(
        data, filename, mime, "Old .doc format: save it as .docx and attach it again"
    )
