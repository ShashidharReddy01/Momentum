"""File kinds from a MIME type and a file name (spec §3.2). Pure; used by the inventory, the
Files tab filters and the parsers' dispatch."""

from __future__ import annotations

from typing import Literal

FileKind = Literal[
    "document", "spreadsheet", "presentation", "pdf", "image", "text", "email", "archive", "other"
]
FILE_KINDS: tuple[FileKind, ...] = (
    "document",
    "spreadsheet",
    "presentation",
    "pdf",
    "image",
    "text",
    "email",
    "archive",
    "other",
)

_BY_EXT: dict[str, FileKind] = {
    **dict.fromkeys(("docx", "docm", "doc", "rtf", "odt", "pages", "dotx"), "document"),
    **dict.fromkeys(("xlsx", "xlsm", "xltx", "xls", "csv", "tsv", "ods", "numbers"), "spreadsheet"),
    **dict.fromkeys(("pptx", "pptm", "ppt", "odp", "key"), "presentation"),
    "pdf": "pdf",
    **dict.fromkeys(
        ("png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff", "heic", "avif", "svg"), "image"
    ),
    **dict.fromkeys(
        ("txt", "md", "markdown", "log", "json", "xml", "yaml", "yml", "html", "htm"), "text"
    ),
    **dict.fromkeys(("eml", "msg"), "email"),
    **dict.fromkeys(("zip", "7z", "rar", "tar", "gz"), "archive"),
}

_BY_MIME_PREFIX: tuple[tuple[str, FileKind], ...] = (
    ("application/pdf", "pdf"),
    ("image/", "image"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml", "document"),
    ("application/msword", "document"),
    ("application/rtf", "document"),
    ("application/vnd.openxmlformats-officedocument.spreadsheetml", "spreadsheet"),
    ("application/vnd.ms-excel", "spreadsheet"),
    ("text/csv", "spreadsheet"),
    ("application/vnd.openxmlformats-officedocument.presentationml", "presentation"),
    ("application/vnd.ms-powerpoint", "presentation"),
    ("message/rfc822", "email"),
    ("application/vnd.ms-outlook", "email"),
    ("application/zip", "archive"),
    ("text/", "text"),
    ("application/json", "text"),
)


def extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def kind_of(mime: str, filename: str) -> FileKind:
    """The extension wins when it's known (a .xlsx is a zip to a byte sniffer); else the MIME."""
    ext = extension(filename)
    if ext in _BY_EXT:
        return _BY_EXT[ext]
    for prefix, kind in _BY_MIME_PREFIX:
        if mime.startswith(prefix):
            return kind
    return "other"


def extensions_of(kind: FileKind) -> list[str]:
    return sorted(e for e, k in _BY_EXT.items() if k == kind)
