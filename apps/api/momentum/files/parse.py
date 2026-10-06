"""Phase 7.5 (spec §4.2): one entry point, ``parse_bytes``, from a file's bytes to a
``ParseResult``. Safety checks run first (``safety.py``); every failure becomes a status with a
plain-English warning, never an exception for the caller."""

from __future__ import annotations

from collections.abc import Callable

from momentum.core.telemetry import get_logger
from momentum.files.kinds import extension, kind_of
from momentum.files.model import ParseResult
from momentum.files.parsers import archive, email, images, pdf, sheets, slides, text, word
from momentum.files.parsers.base import Builder, unsupported
from momentum.files.safety import (
    EncryptedFile,
    UnsafeFile,
    check_ole_encryption,
    check_ooxml_xml,
    check_zip,
    is_ole,
    is_zip,
)

log = get_logger("files.parse")

OOXML = {"docx", "docm", "dotx", "dotm", "xlsx", "xlsm", "xltx", "xltm", "pptx", "pptm"}
IMAGES = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff"}
TEXTS = {"txt", "md", "markdown", "log", "json", "xml", "yaml", "yml", "html", "htm"}
NOT_YET = {
    "odt": "OpenDocument text",
    "ods": "OpenDocument spreadsheets",
    "odp": "OpenDocument presentations",
    "heic": "HEIC images",
    "heif": "HEIF images",
    "pages": "Pages documents",
    "numbers": "Numbers spreadsheets",
    "key": "Keynote presentations",
    "ppt": "Old .ppt presentations",
}

Parser = Callable[[bytes, str, str], ParseResult]


def _pick(ext: str, mime: str, max_rows: int) -> Parser | None:
    def rows(fn: Callable[..., ParseResult]) -> Parser:
        return lambda d, f, m: fn(d, f, m, max_rows=max_rows)

    by_ext: dict[str, Parser] = {
        **dict.fromkeys(("docx", "docm", "dotx", "dotm"), word.parse_docx),
        "rtf": word.parse_rtf,
        "doc": word.parse_doc,
        **dict.fromkeys(("xlsx", "xlsm", "xltx", "xltm"), rows(sheets.parse_xlsx)),
        "xls": rows(sheets.parse_xls),
        **dict.fromkeys(("csv", "tsv"), rows(sheets.parse_csv)),
        **dict.fromkeys(("pptx", "pptm"), slides.parse_pptx),
        "pdf": pdf.parse_pdf,
        **dict.fromkeys(IMAGES, images.parse_image),
        **dict.fromkeys(TEXTS, text.parse_text),
        "eml": email.parse_eml,
        "msg": email.parse_msg,
        "zip": archive.parse_zip,
    }
    if ext in by_ext:
        return by_ext[ext]
    if mime == "application/pdf":
        return pdf.parse_pdf
    if mime == "text/csv":
        return rows(sheets.parse_csv)
    if mime.startswith("image/") and mime != "image/svg+xml":
        return images.parse_image
    if mime == "message/rfc822":
        return email.parse_eml
    if mime.startswith("text/") or mime in ("application/json", "application/xml"):
        return text.parse_text
    return None


def parse_bytes(data: bytes, filename: str, mime: str, *, max_rows: int = 200_000) -> ParseResult:
    ext = extension(filename)
    if ext in NOT_YET:
        return unsupported(
            data,
            filename,
            mime,
            f"{NOT_YET[ext]} can't be read yet: export it as PDF, Word or Excel and attach that",
        )
    parser = _pick(ext, mime, max_rows)
    if parser is None:
        return unsupported(
            data,
            filename,
            mime,
            f"This kind of file ({ext or mime}) can't be read: attach a PDF, Word, Excel, "
            "PowerPoint, text, email or image file",
        )
    try:
        if ext in OOXML or ext == "zip":
            if is_ole(data):  # an encrypted Office file is an OLE container, not a zip
                check_ole_encryption(data)
            if not is_zip(data):
                raise UnsafeFile("The file isn't a valid Office document (it may be damaged)")
            check_zip(data)
            if ext in OOXML:
                check_ooxml_xml(data)
        elif ext in ("xls", "msg", "doc") and is_ole(data):
            check_ole_encryption(data)
        return parser(data, filename, mime)
    except EncryptedFile as e:
        b = Builder(data, filename, mime, kind_of(mime, filename))
        b.header.encrypted = True
        b.warn(f"{e}: attach a copy without a password to read it")
        return b.done("encrypted")
    except UnsafeFile as e:
        b = Builder(data, filename, mime, kind_of(mime, filename))
        b.warn(str(e))
        return b.done("failed", error=str(e))
    except Exception as e:
        # a damaged or unusual file: say so, keep the detail in the log (never the content)
        log.warning("file_parse_failed", ext=ext, error=type(e).__name__)
        b = Builder(data, filename, mime, kind_of(mime, filename))
        b.warn("The file couldn't be read: it may be damaged or in an unusual format")
        return b.done("failed", error=f"{type(e).__name__}: {str(e)[:300]}")
