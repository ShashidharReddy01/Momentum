"""The invoice record (spec §9.9): a superset of the COAP notebook's `ExtractedInvoice` (every field
it extracts is here, with the same meaning) plus the spec's vendor, tax, bank and extraction
details. Money is exact (Decimal, stored as strings); identifiers are verbatim; credit notes keep
their negative values."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from momentum.sdk import Money, RecordModel, RecordType
from momentum_pack_bernie.checks_math import recheck

DocumentType = Literal["invoice", "credit_note", "proforma", "statement", "other"]
Method = Literal["einvoice", "text", "chunked", "ocr", "vision", "mixed"]


class Vendor(RecordModel):
    name: str
    name_as_printed: str | None = None
    entity_id: str | None = None
    tax_id: str | None = None
    country: str | None = None
    address: str | None = None


class BillTo(RecordModel):
    name: str | None = None
    tax_id: str | None = None


class TaxLine(RecordModel):
    label: str
    rate: Money | None = None
    base: Money | None = None
    amount: Money


class Bank(RecordModel):
    """Never the full account number: a fingerprint (server-side HMAC) and the last four."""

    fingerprint: str | None = None
    last4: str | None = None
    bic: str | None = None


class Line(RecordModel):
    """One goods/services line (never a tax, subtotal, total, discount or rounding row)."""

    n: int
    description: str
    sku: str | None = None
    quantity: Money | None = None
    unit: str | None = None
    unit_price: Money | None = None
    amount: Money | None = None
    tax_rate: Money | None = None
    period_start: date | None = None
    period_end: date | None = None


class Extraction(RecordModel):
    method: Method
    pages: int = 0
    text_pages: list[int] = []
    ocr_pages: list[int] = []
    vision_pages: list[int] = []
    chunks: int = 1
    attempts: int = 0
    model_alias: str | None = None
    text_confidence: float | None = None


class InvoiceV1(RecordModel):
    document_type: DocumentType = "invoice"
    vendor: Vendor
    bill_to: BillTo | None = None
    invoice_number: str | None = None
    po_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    payment_terms: str | None = None
    currency: str | None = None
    subtotal: Money | None = None
    tax_amount: Money | None = None
    tax_lines: list[TaxLine] = []
    discount: Money | None = None
    shipping: Money | None = None
    stated_total: Money | None = None
    amount_due: Money | None = None
    period_start: date | None = None
    period_end: date | None = None
    bank: Bank | None = None
    lines: list[Line] = []
    source_language: str | None = None
    was_translated: bool = False
    extraction: Extraction | None = None
    notes: list[str] = []


def _recheck(data: dict[str, Any]) -> list[dict[str, Any]]:
    return recheck(data)


INVOICE = RecordType(
    key="invoice",
    version=1,
    model=InvoiceV1,
    label="Invoice",
    title="{vendor.name} {invoice_number}",
    identity=("vendor.entity_id", "invoice_number"),
    money=(
        "subtotal",
        "tax_amount",
        "discount",
        "shipping",
        "stated_total",
        "amount_due",
        "tax_lines[].base",
        "tax_lines[].amount",
        "lines[].unit_price",
        "lines[].amount",
    ),
    currency_field="currency",
    dates=(
        "invoice_date",
        "due_date",
        "period_start",
        "period_end",
        "lines[].period_start",
        "lines[].period_end",
    ),
    arrays={"lines": "Lines", "tax_lines": "Tax"},
    columns=("vendor.name", "invoice_number", "invoice_date", "stated_total", "currency"),
    task_fields={
        "Vendor": "vendor.name",
        "Invoice #": "invoice_number",
        "Invoice date": "invoice_date",
        "Amount": "stated_total",
        "Currency": "currency",
    },
    classification="financial",
    search=("vendor.name", "invoice_number", "po_number", "lines[].description"),
    amount="stated_total",
    occurred_on="invoice_date",
    recheck_fn=_recheck,
)
