"""Phase 7.5 (spec §4.6): safety limits for reading files. Enforced before and around parsing.

- **Never executed:** macros, formulas, embedded OLE objects, PDF JavaScript and links are only
  ever read as data. Nothing in ``momentum.files`` starts a process or automates an application.
- **Zip bombs:** a zip-based file (OOXML, .zip) may unpack to at most 250 MB in total, at a ratio
  of at most 100:1 over its compressed size, checked from the central directory before anything
  is decompressed.
- **XML bombs:** OOXML never needs a DTD, so any XML part declaring a ``<!DOCTYPE`` or
  ``<!ENTITY`` is refused before a parser sees it; standalone XML goes through ``defusedxml``.
- **Encrypted** Office files (an OLE container with ``EncryptionInfo``) and PDFs are reported as
  encrypted; no password is ever asked for or stored.
- **Images:** at most 40 megapixels (checked from the header, before decoding).
- **Output caps:** 2 MB of text per file and ``MOMENTUM_FILE_PARSE_MAX_ROWS`` rows per sheet;
  more is marked truncated. Each parse runs in a worker thread with a timeout (``cache.py``).
"""

from __future__ import annotations

import io
import zipfile

MAX_UNZIPPED_BYTES = 250 * 1024 * 1024
MAX_ZIP_RATIO = 100
MAX_TEXT_CHARS = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_COLUMNS = 100
XML_SNIFF_BYTES = 4096


class UnsafeFile(Exception):
    """The file was refused before parsing (a bomb, a forbidden construct)."""


class EncryptedFile(Exception):
    """The file is password-protected."""


def is_zip(data: bytes) -> bool:
    return data[:4] == b"PK\x03\x04"


def is_ole(data: bytes) -> bool:
    return data[:8] == bytes.fromhex("D0CF11E0A1B11AE1")


def check_zip(data: bytes) -> None:
    """Refuse a zip whose declared contents are too big or too compressed. Reads only the
    central directory: nothing is decompressed here."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
    except zipfile.BadZipFile as e:
        raise UnsafeFile("The file looks like a zip archive but can't be opened") from e
    total = sum(i.file_size for i in infos)
    if total > MAX_UNZIPPED_BYTES:
        raise UnsafeFile("The file unpacks to more than 250 MB")
    if total > MAX_ZIP_RATIO * max(len(data), 1):
        raise UnsafeFile("The file is compressed far more than real documents are (a zip bomb?)")
    for i in infos:
        if (
            i.compress_size
            and i.file_size > MAX_ZIP_RATIO * i.compress_size
            and i.file_size > 1 << 20
        ):
            raise UnsafeFile("A part of the file is compressed far more than real documents are")


def check_ooxml_xml(data: bytes) -> None:
    """Refuse an OOXML package with a DTD or entity declaration in any XML part. Each part's
    first 4 KB are read (that's where a DOCTYPE must be), after ``check_zip`` bounded the size."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith((".xml", ".rels", ".vml")):
                continue
            with z.open(info) as f:
                head = f.read(XML_SNIFF_BYTES)
            low = head.lower()
            if b"<!doctype" in low or b"<!entity" in low:
                raise UnsafeFile("The file contains XML declarations real documents never use")


def check_ole_encryption(data: bytes) -> None:
    """An encrypted .docx/.xlsx/.pptx is an OLE container with an EncryptionInfo stream; a
    legacy file with a password has an encryption flag we report the same way."""
    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception:  # not a readable OLE file: the parser says so
        return
    try:
        names = {"/".join(p) for p in ole.listdir()}
        if "EncryptionInfo" in names or "EncryptedPackage" in names:
            raise EncryptedFile("The file is password-protected")
    finally:
        ole.close()


def check_image_header(data: bytes) -> tuple[int, int]:
    """Width and height from the header, without decoding; refuse > 40 megapixels."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
    if w * h > MAX_IMAGE_PIXELS:
        raise UnsafeFile(f"The image is {w} x {h} pixels, over the 40-megapixel limit")
    return w, h


def cap_text(text: str, used: int) -> tuple[str, bool]:
    """Keep the total extracted text within MAX_TEXT_CHARS; True when this piece was cut."""
    room = MAX_TEXT_CHARS - used
    if room <= 0:
        return "", True
    if len(text) > room:
        return text[:room], True
    return text, False
