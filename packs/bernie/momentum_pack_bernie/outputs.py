"""What Bernie leaves behind (spec §9.3.18-19 and the batch catalogue, §9.3 end): task fields, the
task's new name, the approval subtask's text, the hold ask, the comment, and the catalogue CSV in
the COAP notebook's column order. Pure functions; the pipeline runs the effects."""

from __future__ import annotations

import contextlib
import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any

STATUS_LABELS = {
    "ready": "Ready",
    "needs_review": "Needs review",
    "approved": "Approved",
    "rejected": "Rejected",
    "hold": "On hold",
}

# the notebook's `_CSV_COLUMNS`, in order (catalogue.py)
CSV_COLUMNS = [
    "document",
    "vendor_id",
    "status",
    "document_type",
    "line_number",
    "description",
    "quantity",
    "unit_price",
    "amount",
    "period_start",
    "period_end",
    "currency",
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "subtotal",
    "tax_amount",
    "stated_total",
    "confidence",
]

BANK_CONFIRMED = "Confirmed with the vendor: update bank details"
REJECT = "Reject the invoice"
NOT_DUPLICATE = "It isn't a duplicate: carry on"


def money(amount: Any, currency: str | None) -> str:
    try:
        text = f"{Decimal(str(amount)):,.2f}"
    except (InvalidOperation, ValueError):
        return f"{currency or ''} ?".strip()
    return f"{currency or ''} {text}".strip()


def task_title(data: dict[str, Any]) -> str:
    """``Northwind Data · INV-2041 · GBP 1,250.00``"""
    parts = [
        data.get("vendor", {}).get("name") or "Unknown vendor",
        data.get("invoice_number") or "no number",
    ]
    if data.get("stated_total") is not None:
        parts.append(money(data["stated_total"], data.get("currency")))
    return " · ".join(parts)[:500]


def approval_title(data: dict[str, Any]) -> str:
    """``Approve Northwind Data INV-2041 (GBP 1,250.00)``"""
    who = data.get("vendor", {}).get("name") or "the invoice"
    number = data.get("invoice_number") or ""
    total = (
        f" ({money(data['stated_total'], data.get('currency'))})"
        if data.get("stated_total") is not None
        else ""
    )
    return f"Approve {who} {number}{total}".replace("  ", " ")[:500]


def task_fields(data: dict[str, Any], status: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "Vendor": data.get("vendor", {}).get("name"),
        "Invoice #": data.get("invoice_number"),
        "Invoice date": data.get("invoice_date"),
        "Currency": data.get("currency"),
        "Invoice status": STATUS_LABELS.get(status, "Needs review"),
    }
    with contextlib.suppress(KeyError, InvalidOperation, ValueError, TypeError):
        out["Amount"] = float(Decimal(str(data["stated_total"])))
    return {k: v for k, v in out.items() if v not in (None, "")}


def _failed(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"block": 0, "warn": 1, "info": 2}
    return sorted((c for c in checks if not c["passed"]), key=lambda c: order.get(c["severity"], 3))


def check_lines(checks: list[dict[str, Any]], limit: int = 5) -> list[str]:
    return [
        f"- {'✗' if c['severity'] == 'block' else '!' if c['severity'] == 'warn' else 'i'} "
        f"{c.get('detail') or c['title']}"
        for c in _failed(checks)[:limit]
    ]


def approval_description(
    data: dict[str, Any], checks: list[dict[str, Any]], decision: dict[str, Any], link: str
) -> str:
    lines = [
        f"{task_title(data)}, dated {data.get('invoice_date') or '?'}, "
        f"{len(data.get('lines') or [])} line(s).",
        f"Why a person approves: {decision.get('reason')}",
    ]
    failing = check_lines(checks)
    lines += ["", "Checks to look at:", *failing] if failing else ["", "All checks passed."]
    lines += ["", f"Review it: {link}"]
    return "\n".join(lines)


def hold_ask(data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    who = data.get("vendor", {}).get("name") or "this vendor"
    number = data.get("invoice_number") or ""
    if decision.get("rule_id") == "block_bank_change":
        return {
            "title": f"Bank details changed for {who}"[:200],
            "body": f"{decision.get('reason')} Confirm it with the vendor through a known contact "
            "(not the details on this invoice) before approving.",
            "options": [
                {"value": BANK_CONFIRMED, "label": BANK_CONFIRMED},
                {"value": REJECT, "label": REJECT},
            ],
        }
    return {
        "title": f"Possible duplicate: {who} {number}".strip()[:200],
        "body": f"{decision.get('reason')} Is this the same invoice?",
        "options": [
            {"value": REJECT, "label": "It's a duplicate: reject it"},
            {"value": NOT_DUPLICATE, "label": NOT_DUPLICATE},
        ],
    }


def comment(
    data: dict[str, Any],
    checks: list[dict[str, Any]],
    decision: dict[str, Any],
    link: str,
    *,
    status: str,
    approver: str | None = None,
) -> str:
    head = f"Read {task_title(data)} ({len(data.get('lines') or [])} line(s)). Review it: {link}"
    verdict = decision.get("decision")
    if verdict == "allow":
        tail = f"Approved by policy (rule `{decision.get('rule_id')}`): {decision.get('reason')}"
    elif verdict == "hold":
        tail = f"On hold: {decision.get('reason')}"
    elif approver:
        tail = f"Sent to {approver} for approval: {decision.get('reason')}"
    else:
        tail = f"Needs a person: {decision.get('reason')}"
    failing = check_lines(checks, 3)
    parts = [head, "", tail]
    if failing:
        parts += ["", *failing]
    if status == "needs_review" and verdict != "hold":
        parts += ["", "It's in review."]
    return "\n".join(parts)


def catalogue_csv(rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    """The notebook's catalogue: one row per line item, every column transcribed (never
    computed). Documents with no record or no lines are listed in ``excluded`` with a reason."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    excluded: list[dict[str, str]] = []
    for r in rows:
        data = r.get("data")
        if not data:
            excluded.append(
                {"document": r.get("file") or "?", "reason": r.get("error") or "no record was made"}
            )
            continue
        if not data.get("lines"):
            excluded.append({"document": r.get("file") or "?", "reason": "no line items"})
            continue
        for li in data["lines"]:
            writer.writerow(
                {
                    "document": r.get("file"),
                    "vendor_id": data.get("vendor", {}).get("entity_id"),
                    "status": r.get("status"),
                    "document_type": data.get("document_type"),
                    "line_number": li.get("n"),
                    "description": _safe(li.get("description")),
                    "quantity": li.get("quantity"),
                    "unit_price": li.get("unit_price"),
                    "amount": li.get("amount"),
                    "period_start": li.get("period_start"),
                    "period_end": li.get("period_end"),
                    "currency": data.get("currency"),
                    "vendor_name": _safe(data.get("vendor", {}).get("name")),
                    "invoice_number": _safe(data.get("invoice_number")),
                    "invoice_date": data.get("invoice_date"),
                    "subtotal": data.get("subtotal"),
                    "tax_amount": data.get("tax_amount"),
                    "stated_total": data.get("stated_total"),
                    "confidence": r.get("confidence"),
                }
            )
    return buffer.getvalue(), excluded


def _safe(text: Any) -> Any:
    """Text that a spreadsheet would run as a formula stays text."""
    if isinstance(text, str) and text[:1] in ("=", "+", "-", "@") and not _number(text):
        return "'" + text
    return text


def _number(text: str) -> bool:
    try:
        Decimal(text)
    except InvalidOperation:
        return False
    return True
