"""Files in, single invoice documents out (spec §9.3.2): a port of the COAP notebook's `pdf_utils`
(zip limits, sha256 dedupe, vendor hints from folder names, and its invoice-boundary detection
with the "different invoice number" rule and the PAGE N OF M guard, unchanged), with pypdf for
splitting instead of PyMuPDF (AGPL), plus .eml/.msg attachments, images, e-invoice XML, and
zip-bomb guards. Deterministic: no model calls."""

from __future__ import annotations

import email
import email.policy
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field

MAX_ARCHIVE_ENTRIES = 500
MAX_ENTRY_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_RATIO = 100  # uncompressed / compressed, per entry: above this it's treated as a zip bomb

PDF = "application/pdf"
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
XML_TYPES = {".xml": "application/xml"}

_BOUNDARY_KEYWORDS = ("INVOICE", "TAX INVOICE", "INVOICE NUMBER", "INV-", "BILL TO", "INVOICE DATE")
_PAGE_OF = re.compile(r"PAGE\s+(\d+)\s+OF\s+(\d+)")


@dataclass
class Document:
    """One invoice candidate: a whole file, or one split-out range of a multi-invoice PDF."""

    name: str
    data: bytes
    mime: str
    sha256: str
    page_count: int
    parent: str | None = None
    vendor_hint: str | None = None
    page_range: tuple[int, int] | None = None  # 1-based, inclusive, within the parent


@dataclass
class Ingested:
    documents: list[Document] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


class IngestError(ValueError):
    """The upload can't be safely unpacked at all."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ext(name: str) -> str:
    m = re.search(r"\.[A-Za-z0-9]+$", name)
    return m.group(0).lower() if m else ""


def slug_folder(entry_name: str) -> str | None:
    """The immediate folder of an archive entry, slugified ("Cboe Global Markets/x.pdf" →
    "cboe_global_markets"); a vendor hint the notebook trusted over a model's guess."""
    parts = entry_name.replace("\\", "/").split("/")
    if len(parts) < 2 or not parts[-2].strip():
        return None
    s = re.sub(r"[^a-z0-9]+", "_", parts[-2].strip().lower()).strip("_")
    return s or None


# ---------------------------------------------------------------- PDF primitives (pypdf/pdfplumber)


def pdf_page_texts(data: bytes) -> list[str]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def pdf_page_count(data: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(data)).pages)


def pdf_is_encrypted(data: bytes) -> bool:
    from pypdf import PdfReader

    try:
        return bool(PdfReader(io.BytesIO(data)).is_encrypted)
    except Exception:
        return False


def split_pdf(data: bytes, ranges: list[tuple[int, int]]) -> list[bytes]:
    """`ranges` are 0-based inclusive page ranges."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(data))
    out: list[bytes] = []
    for start, end in ranges:
        w = PdfWriter()
        for i in range(start, end + 1):
            w.add_page(reader.pages[i])
        buf = io.BytesIO()
        w.write(buf)
        out.append(buf.getvalue())
    return out


def invoice_number_on_page(text: str) -> str | None:
    """Best effort, only to decide whether a page starts a different invoice (never used for
    extraction). The notebook's two patterns, unchanged."""
    for pattern in (
        r"invoice\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{2,19})",
        r"\b(INV-[A-Z0-9\-]{2,19})\b",
    ):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return None


def invoice_boundaries(page_texts: list[str]) -> list[int]:
    """0-based indices of pages that start a NEW invoice (page 0 always does). A page only starts
    a new invoice when it carries invoice keywords **and** a different invoice number than the
    one in progress; "Page 2 of 3" pages never do; when no number can be read, don't split (an
    under-split is caught by the total check, a false split silently makes two bad invoices)."""
    boundaries = [0]
    current = invoice_number_on_page((page_texts[0] if page_texts else "")[:800])
    for i in range(1, len(page_texts)):
        head = (page_texts[i] or "")[:400].upper()
        m = _PAGE_OF.search(head)
        if m and int(m.group(1)) > 1:
            continue
        if not any(k in head for k in _BOUNDARY_KEYWORDS):
            continue
        number = invoice_number_on_page((page_texts[i] or "")[:800])
        if current is None:
            current = number
        elif number and number != current:
            boundaries.append(i)
            current = number
    return boundaries


def split_invoices(name: str, data: bytes) -> list[tuple[str, bytes, tuple[int, int] | None]]:
    count = pdf_page_count(data)
    if count <= 1:
        return [(name, data, None)]
    bounds = invoice_boundaries(pdf_page_texts(data))
    if len(bounds) <= 1:
        return [(name, data, None)]
    ranges = [
        (bounds[i], bounds[i + 1] - 1 if i + 1 < len(bounds) else count - 1)
        for i in range(len(bounds))
    ]
    stem = name.rsplit(".", 1)[0]
    parts = split_pdf(data, ranges)
    return [
        (f"{stem}__part{i + 1}.pdf", part, (r[0] + 1, r[1] + 1))
        for i, (part, r) in enumerate(zip(parts, ranges, strict=True))
    ]


# ---------------------------------------------------------------- containers


def _zip_entries(name: str, data: bytes) -> list[tuple[str, bytes]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise IngestError(f"{name} isn't a readable zip: {e}") from e
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise IngestError(
            f"{name} holds {len(infos)} files; the most Bernie takes in one go is "
            f"{MAX_ARCHIVE_ENTRIES}"
        )
    total = sum(i.file_size for i in infos)
    if total > MAX_ARCHIVE_BYTES:
        raise IngestError(f"{name} unpacks to more than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB")
    out: list[tuple[str, bytes]] = []
    for info in infos:
        if info.file_size > MAX_ENTRY_BYTES:
            raise IngestError(f"{info.filename} in {name} is larger than 25 MB")
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
            raise IngestError(f"{info.filename} in {name} looks like a zip bomb")
        raw = zf.read(info)
        if len(raw) > MAX_ENTRY_BYTES:
            raise IngestError(f"{info.filename} in {name} is larger than 25 MB")
        out.append((info.filename, raw))
    return out


def _eml_attachments(data: bytes) -> list[tuple[str, bytes]]:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    out: list[tuple[str, bytes]] = []
    for part in msg.walk():
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            out.append((filename, payload))
    return out


def _msg_attachments(data: bytes) -> list[tuple[str, bytes]]:
    import extract_msg

    m = extract_msg.openMsg(io.BytesIO(data))
    try:
        out: list[tuple[str, bytes]] = []
        for a in m.attachments:
            name = getattr(a, "longFilename", None) or getattr(a, "shortFilename", None)
            payload = getattr(a, "data", None)
            if name and isinstance(payload, bytes):
                out.append((str(name), payload))
        return out
    finally:
        m.close()


def ingest(files: list[tuple[str, bytes]], *, known_sha256: set[str] | None = None) -> Ingested:
    """Every file (and every file inside a zip or an email) → invoice documents. Anything that
    can't be used is listed in `skipped` with a reason; nothing is dropped silently."""
    result = Ingested()
    seen = set(known_sha256 or ())

    def add(name: str, data: bytes, hint: str | None, parent: str | None) -> None:
        ext = _ext(name)
        if not data:
            result.skipped.append({"file": name, "reason": "The file is empty"})
            return
        if ext == ".zip":
            for inner, raw in _zip_entries(name, data):
                add(inner, raw, slug_folder(inner) or hint, name)
            return
        if ext == ".eml":
            for inner, raw in _eml_attachments(data):
                add(inner, raw, hint, name)
            return
        if ext == ".msg":
            for inner, raw in _msg_attachments(data):
                add(inner, raw, hint, name)
            return
        if ext == ".pdf" or data[:5] == b"%PDF-":
            if pdf_is_encrypted(data):
                result.skipped.append(
                    {
                        "file": name,
                        "reason": "The PDF is password-protected; attach an unprotected copy",
                    }
                )
                return
            try:
                parts = split_invoices(name, data)
            except Exception as e:
                result.skipped.append({"file": name, "reason": f"The PDF can't be read: {e}"[:300]})
                return
            for part_name, part, rng in parts:
                digest = sha256(part)
                if digest in seen:
                    result.skipped.append(
                        {"file": part_name, "reason": "The same file is already in this batch"}
                    )
                    continue
                seen.add(digest)
                result.documents.append(
                    Document(
                        name=part_name,
                        data=part,
                        mime=PDF,
                        sha256=digest,
                        page_count=pdf_page_count(part),
                        parent=parent if part_name == name else (parent or name),
                        vendor_hint=hint,
                        page_range=rng,
                    )
                )
            return
        if ext in IMAGE_TYPES or ext in XML_TYPES:
            digest = sha256(data)
            if digest in seen:
                result.skipped.append(
                    {"file": name, "reason": "The same file is already in this batch"}
                )
                return
            seen.add(digest)
            result.documents.append(
                Document(
                    name=name,
                    data=data,
                    mime=IMAGE_TYPES.get(ext) or XML_TYPES[ext],
                    sha256=digest,
                    page_count=1 if ext in IMAGE_TYPES else 0,
                    parent=parent,
                    vendor_hint=hint,
                )
            )
            return
        result.skipped.append(
            {
                "file": name,
                "reason": "Not an invoice file Bernie reads (PDF, image, zip, XML, email)",
            }
        )

    for name, data in files:
        add(name, data, slug_folder(name), None)
    return result
