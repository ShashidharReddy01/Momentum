"""Phase 7.5 (spec §4.1): what reading a file produces.

A ``DocumentModel`` is the structured, human-citable content of one file: an outline, text and
table blocks with **locators** (``p3``, ``s:Budget!A1:F40``, ``slide 4``, ``table 2``,
``§ Scope > Out of scope``), sheet summaries, macros as text, email headers, archive listings and
warnings. Sheet rows are kept apart (``ParseResult.rows``): they can be large, so the cache stores
them gzipped in the storage backend and the model in the database.

``PARSER_VERSION`` goes up whenever a parser's output changes, which invalidates every cached
parse.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from momentum.files.kinds import FileKind

PARSER_VERSION = 1

ParseStatus = Literal["ok", "failed", "unsupported", "encrypted"]
ColumnType = Literal["number", "percent", "date", "bool", "text", "empty"]
# a cell as stored: typed where the format has types (xlsx), text where it doesn't (csv)
Cell = str | int | float | bool | None


class FileHeader(BaseModel):
    attachment_id: uuid.UUID | None = None
    filename: str
    mime: str
    kind: FileKind
    size: int
    pages: int | None = None
    sheets: int | None = None
    slides: int | None = None
    encrypted: bool = False
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class OutlineItem(BaseModel):
    id: str
    title: str
    level: int = 1
    locator: str


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    id: str
    locator: str
    text: str
    style: str | None = None


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    id: str
    locator: str
    title: str | None = None
    columns: list[str]
    rows: list[list[str]]
    row_count: int
    truncated: bool = False


class ImageRef(BaseModel):
    type: Literal["image"] = "image"
    id: str
    locator: str
    width: int | None = None
    height: int | None = None
    alt: str | None = None
    page: int | None = None
    slide: int | None = None
    # a PDF page with almost no text and a picture over most of it: read it by looking at it
    scanned: bool = False


Block = Annotated[TextBlock | TableBlock | ImageRef, Field(discriminator="type")]


class SheetColumn(BaseModel):
    name: str
    letter: str
    inferred_type: ColumnType


class FormulaCell(BaseModel):
    cell: str
    formula: str
    cached: Cell = None


class SheetInfo(BaseModel):
    name: str
    dims: str
    header_row_guess: int  # 1-based sheet row of the header (0 = no header found)
    columns: list[SheetColumn]
    row_count: int  # data rows below the header
    has_formulas: bool = False
    formulas: list[FormulaCell] = Field(default_factory=list)  # first 500
    formulas_without_values: int = 0
    named_ranges: list[str] = Field(default_factory=list)
    charts_count: int = 0
    hidden: bool = False
    merged_cells: int = 0
    truncated: bool = False
    data_ref: str  # key of this sheet's rows in ParseResult.rows / the stored rows


class MacroModule(BaseModel):
    name: str
    kind: str
    lines: int
    code: str  # at most MACRO_LINES lines


class MacroFlag(BaseModel):
    keyword: str
    meaning: str
    module: str | None = None


class MacroInfo(BaseModel):
    present: bool = False
    modules: list[MacroModule] = Field(default_factory=list)
    flags: list[MacroFlag] = Field(default_factory=list)


class EmailInfo(BaseModel):
    sender: str | None = None
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    subject: str | None = None
    date: str | None = None
    attachments: list[dict[str, str | int]] = Field(default_factory=list)


class ArchiveEntry(BaseModel):
    path: str
    size: int


class ArchiveInfo(BaseModel):
    entries: list[ArchiveEntry] = Field(default_factory=list)
    skipped_reason: str | None = None


class DocumentModel(BaseModel):
    parser_version: int = PARSER_VERSION
    file: FileHeader
    outline: list[OutlineItem] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    sheets: list[SheetInfo] = Field(default_factory=list)
    macros: MacroInfo = Field(default_factory=MacroInfo)
    email: EmailInfo | None = None
    archive: ArchiveInfo | None = None

    def sheet(self, name: str) -> SheetInfo | None:
        low = name.strip().lower()
        return next((s for s in self.sheets if s.name.lower() == low), None)

    def text_length(self) -> int:
        return sum(len(b.text) for b in self.blocks if isinstance(b, TextBlock))


@dataclass
class ParseResult:
    status: ParseStatus
    model: DocumentModel
    # sheet rows by SheetInfo.data_ref; each row a list of cells starting at column A, row 1
    rows: dict[str, list[list[Cell]]] = field(default_factory=dict)
    error: str | None = None


def cell_value(v: object) -> Cell:
    """A spreadsheet library's value as a stored cell: numbers and booleans stay typed, dates
    become ISO text, anything else text."""
    if v is None or isinstance(v, bool | int | float | str):
        return v
    if isinstance(v, datetime):
        return (
            v.isoformat(sep=" ")
            if (v.hour, v.minute, v.second) != (0, 0, 0)
            else v.date().isoformat()
        )
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def column_letter(index: int) -> str:
    """0-based column index → A, B, …, Z, AA, …"""
    s = ""
    n = index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def column_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1
