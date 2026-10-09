"""Structured extraction (spec §9.3.9), ported from the COAP notebook's `extract.py`:
"transcribe, do not compute". Paths, as in the notebook:

- **text** — every page readable (text layer or OCR) and at most 8 pages: one call over all of it;
- **chunked** — more than 8 pages: 4 pages per call, each extracting every line it sees, merged
  (lines concatenated and renumbered, header fields last-present wins, the lowest confidence);
  this is what turned the notebook's 13-of-396-lines truncation into all 396;
- **vision** / **mixed** — pages that stayed poor after OCR go as images, at most 4 pages per call,
  with the text of that slice's readable pages beside them.

The model's answer (`Extracted`) is mapped to the invoice record in code; numbers stay exactly
as transcribed (Decimal from the model's decimal string or number)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from momentum_pack_bernie.read import Reading

SINGLE_CALL_PAGES = 8  # the notebook's LARGE_INVOICE_PAGE_THRESHOLD
PAGES_PER_CHUNK = 4  # the notebook's PAGE_CHUNK_SIZE
CHUNK_PAGES = 4  # pages per vision call (each an image)


class ExtractedLine(BaseModel):
    model_config = ConfigDict(extra="ignore")
    line_number: int
    description: str
    sku: str | None = None
    quantity: float | str | None = None
    unit: str | None = None
    unit_price: float | str | None = None
    amount: float | str | None = None
    tax_rate: float | str | None = None
    period_start: str | None = None
    period_end: str | None = None


class ExtractedTax(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: str
    rate: float | str | None = None
    base: float | str | None = None
    amount: float | str


class Extracted(BaseModel):
    """What the model is asked for (one invoice or credit note)."""

    model_config = ConfigDict(extra="ignore")
    document_type: str = Field(
        default="invoice", description="invoice, credit_note, proforma, statement or other"
    )
    vendor_name: str | None = None
    vendor_name_as_printed: str | None = None
    vendor_tax_id: str | None = None
    vendor_country: str | None = Field(default=None, description="ISO 3166 two-letter code")
    vendor_address: str | None = None
    bill_to_name: str | None = None
    invoice_number: str | None = None
    po_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    payment_terms: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    currency: str | None = None
    line_items: list[ExtractedLine] = []
    subtotal: float | str | None = None
    tax_amount: float | str | None = None
    tax_lines: list[ExtractedTax] = []
    discount: float | str | None = None
    shipping: float | str | None = None
    stated_total: float | str | None = None
    amount_due: float | str | None = None
    bank_account: str | None = None
    bank_bic: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    source_language: str | None = None
    was_translated: bool = False
    extraction_notes: list[str] = []


# ---------------------------------------------------------------- prompts


def skills_block(skills: list[Any]) -> str:
    """Vendor skills as the prompt's "strong prior" block (hints, rules, field maps, up to two
    worked examples)."""
    if not skills:
        return ""
    lines: list[str] = []
    examples = 0
    for s in skills:
        c = s.content
        if s.kind == "hint":
            lines.append(f"- hint{f' ({s.field})' if s.field else ''}: {c.get('text')}")
        elif s.kind == "rule":
            lines.append("- rule: " + ", ".join(f"{k} = {v}" for k, v in c.items()))
        elif s.kind == "field_map":
            lines.append(f"- the label “{c.get('label')}” is the field {c.get('field')}")
        elif s.kind == "example" and examples < 2:
            examples += 1
            lines.append(f"- worked example: {c.get('input')} → {c.get('output')}")
    return "vendor skills (strong prior, not truth):\n" + "\n".join(lines) + "\n\n" if lines else ""


def page_block(reading: Reading, pages: list[int]) -> str:
    parts = []
    for p in reading.pages:
        if p.n in pages and p.source != "vision":
            parts.append(f"=== Page {p.n} ===\n{p.text}")
        elif p.n in pages:
            parts.append(f"=== Page {p.n} === (image below)")
    return "\n".join(parts)


def user_content(
    reading: Reading, pages: list[int], skills: list[Any], images: list[bytes], *, slice_of: int
) -> Any:
    head = skills_block(skills)
    scope = "slice" if slice_of > len(pages) else "document"
    head += f"pages in this {scope}: {pages[0]}-{pages[-1]} of {slice_of}\n\n"
    text = f"{head}<untrusted_document>\n{page_block(reading, pages)}\n</untrusted_document>"
    if not images:
        return text
    import base64

    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for img in images:
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()},
            }
        )
    return parts


def chunks(page_count: int, size: int) -> list[list[int]]:
    return [list(range(s, min(s + size, page_count + 1))) for s in range(1, page_count + 1, size)]


def plan(reading: Reading) -> tuple[str, list[list[int]]]:
    """Which path, and the page groups (1-based) for each model call."""
    n = len(reading.pages)
    vision = reading.vision_pages
    if not vision:
        if n <= SINGLE_CALL_PAGES:
            return "text", [list(range(1, n + 1))]
        return "chunked", chunks(n, PAGES_PER_CHUNK)
    method = "vision" if len(vision) == n else "mixed"
    if n <= CHUNK_PAGES:
        return method, [list(range(1, n + 1))]
    return method, chunks(n, CHUNK_PAGES)


# ---------------------------------------------------------------- merging (the notebook's)


def _last_present(values: list[Any]) -> Any:
    for v in reversed(values):
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        return v
    return None


def merge(results: list[Extracted]) -> Extracted:
    if len(results) == 1:
        return results[0]
    lines: list[ExtractedLine] = []
    for r in results:
        lines += r.line_items
    for i, li in enumerate(lines, start=1):
        li.line_number = i
    header = {
        f: _last_present([getattr(r, f) for r in results])
        for f in (
            "vendor_name",
            "vendor_name_as_printed",
            "vendor_tax_id",
            "vendor_country",
            "vendor_address",
            "bill_to_name",
            "invoice_number",
            "po_number",
            "invoice_date",
            "due_date",
            "payment_terms",
            "period_start",
            "period_end",
            "currency",
            "subtotal",
            "tax_amount",
            "discount",
            "shipping",
            "stated_total",
            "amount_due",
            "bank_account",
            "bank_bic",
            "source_language",
        )
    }
    tax_lines = next((r.tax_lines for r in reversed(results) if r.tax_lines), [])
    return Extracted(
        document_type=_last_present([r.document_type for r in results]) or "invoice",
        line_items=lines,
        tax_lines=tax_lines,
        confidence=min(r.confidence for r in results),
        was_translated=any(r.was_translated for r in results),
        extraction_notes=[n for r in results for n in r.extraction_notes]
        + [f"Extracted in {len(results)} page-range chunks (a long invoice)."],
        **header,
    )


# ---------------------------------------------------------------- to the record


def _money(v: Any) -> str | None:
    if v is None or v == "":
        return None
    from decimal import Decimal, InvalidOperation

    text = str(v).strip().replace(" ", "")
    if isinstance(v, str) and "," in text and "." in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")  # 1.234,56
    elif (
        isinstance(v, str)
        and text.count(",") == 1
        and "." not in text
        and len(text.split(",")[1]) in (1, 2)
    ):
        text = text.replace(",", ".")  # 1234,5
    text = text.replace(",", "")
    for sym in ("$", "€", "£", "¥"):
        text = text.replace(sym, "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return format(Decimal(text), "f")
    except InvalidOperation:
        return None


def _date(v: Any) -> str | None:
    from datetime import date

    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        return None


DOC_TYPES = {"invoice", "credit_note", "proforma", "statement", "other"}


def to_record(
    e: Extracted,
    *,
    method: str,
    reading: Reading,
    chunk_count: int,
    vendor_entity_id: str | None,
    vendor_name: str | None,
    model_alias: str,
) -> dict[str, Any]:
    """The invoice record's data (bank details excluded: the account goes to `set_bank` and only
    its last four digits are kept)."""
    printed = e.vendor_name_as_printed or e.vendor_name
    data: dict[str, Any] = {
        "document_type": e.document_type if e.document_type in DOC_TYPES else "other",
        "vendor": {
            "name": vendor_name or e.vendor_name or printed or "Unknown vendor",
            "name_as_printed": printed,
            "entity_id": vendor_entity_id,
            "tax_id": e.vendor_tax_id,
            "country": (e.vendor_country or "").upper()[:2] or None,
            "address": e.vendor_address,
        },
        "bill_to": {"name": e.bill_to_name} if e.bill_to_name else None,
        "invoice_number": (e.invoice_number or "").strip() or None,
        "po_number": e.po_number,
        "invoice_date": _date(e.invoice_date),
        "due_date": _date(e.due_date),
        "payment_terms": e.payment_terms,
        "currency": (e.currency or "").strip().upper() or None,
        "subtotal": _money(e.subtotal),
        "tax_amount": _money(e.tax_amount),
        "tax_lines": [
            {
                "label": t.label,
                "rate": _money(t.rate),
                "base": _money(t.base),
                "amount": _money(t.amount),
            }
            for t in e.tax_lines
            if _money(t.amount) is not None
        ],
        "discount": _money(e.discount),
        "shipping": _money(e.shipping),
        "stated_total": _money(e.stated_total),
        "amount_due": _money(e.amount_due),
        "period_start": _date(e.period_start),
        "period_end": _date(e.period_end),
        "lines": [
            {
                "n": i,
                "description": li.description,
                "sku": li.sku,
                "quantity": _money(li.quantity),
                "unit": li.unit,
                "unit_price": _money(li.unit_price),
                "amount": _money(li.amount),
                "tax_rate": _money(li.tax_rate),
                "period_start": _date(li.period_start),
                "period_end": _date(li.period_end),
            }
            for i, li in enumerate(e.line_items, start=1)
        ],
        "source_language": e.source_language,
        "was_translated": e.was_translated,
        "extraction": {
            "method": method,
            "pages": len(reading.pages),
            "text_pages": reading.text_pages,
            "ocr_pages": reading.ocr_pages,
            "vision_pages": reading.vision_pages,
            "chunks": chunk_count,
            "attempts": 0,
            "model_alias": model_alias,
            "text_confidence": reading.confidence,
        },
        "notes": list(e.extraction_notes),
    }
    if e.bank_account:
        digits = "".join(ch for ch in e.bank_account if ch.isalnum())
        data["bank"] = {"last4": digits[-4:] or None, "bic": e.bank_bic}
    return data
