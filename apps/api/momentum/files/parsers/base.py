"""Shared pieces for parsers: a builder that numbers blocks, keeps the outline and enforces the
text cap, and helpers for tables."""

from __future__ import annotations

from momentum.files.kinds import FileKind, kind_of
from momentum.files.model import (
    Cell,
    DocumentModel,
    FileHeader,
    ImageRef,
    OutlineItem,
    ParseResult,
    ParseStatus,
    TableBlock,
    TextBlock,
)
from momentum.files.safety import cap_text

MAX_TABLE_ROWS = 500  # rows kept in a TableBlock (documents, slides, PDFs); counted beyond that


class Builder:
    def __init__(self, data: bytes, filename: str, mime: str, kind: FileKind | None = None):
        self.header = FileHeader(
            filename=filename, mime=mime, kind=kind or kind_of(mime, filename), size=len(data)
        )
        self.model = DocumentModel(file=self.header)
        self.rows: dict[str, list[list[Cell]]] = {}
        self._n = 0
        self._text = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def warn(self, message: str) -> None:
        if message not in self.header.warnings:
            self.header.warnings.append(message)

    def heading(self, title: str, level: int, locator: str) -> None:
        self.model.outline.append(
            OutlineItem(id=self._id("h"), title=title.strip()[:300], level=level, locator=locator)
        )

    def text(self, text: str, locator: str, style: str | None = None) -> None:
        text = text.strip()
        if not text:
            return
        kept, cut = cap_text(text, self._text)
        if cut:
            self.header.truncated = True
            self.warn("The file has more text than Mo reads at once (2 MB): the rest was cut")
        if not kept:
            return
        self._text += len(kept)
        self.model.blocks.append(
            TextBlock(id=self._id("b"), locator=locator, text=kept, style=style)
        )

    def table(self, rows: list[list[str]], locator: str, title: str | None = None) -> None:
        rows = [[(c or "").strip() for c in r] for r in rows if any((c or "").strip() for c in r)]
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        columns, body = rows[0], rows[1:]
        self.model.blocks.append(
            TableBlock(
                id=self._id("t"),
                locator=locator,
                title=title,
                columns=[c or f"Column {i + 1}" for i, c in enumerate(columns)],
                rows=body[:MAX_TABLE_ROWS],
                row_count=len(body),
                truncated=len(body) > MAX_TABLE_ROWS,
            )
        )

    def image(self, locator: str, **kw: object) -> None:
        self.model.blocks.append(
            ImageRef.model_validate({"id": self._id("i"), "locator": locator, **kw})
        )

    def done(self, status: ParseStatus = "ok", error: str | None = None) -> ParseResult:
        return ParseResult(status=status, model=self.model, rows=self.rows, error=error)


def unsupported(data: bytes, filename: str, mime: str, message: str) -> ParseResult:
    b = Builder(data, filename, mime)
    b.warn(message)
    return b.done("unsupported")


def section_locator(path: list[str]) -> str:
    return "§ " + " > ".join(path) if path else "§ (start)"
