"""Risk checks (spec §9.3.14): deterministic, from the record, the vendor's profile, the bank seen
and the records helpers (duplicates and look-alikes). No model calls."""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from momentum_pack_bernie.checks_math import check, dec
from momentum_pack_bernie.entities import tax_rate

# Text addressed to an AI inside a document (spec §8.7): found in code, not only when the model
# says so (a model that was taken in might not).
_HOSTILE = re.compile(
    r"ignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+instructions"
    r"|disregard\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above)\b"
    r"|(?:note|message|instructions?)\s+(?:to|for)\s+(?:the\s+)?(?:ai|assistant|model|llm|bot)\b"
    r"|\byou\s+are\s+(?:an?\s+)?(?:ai|assistant|language\s+model|llm)\b"
    r"|\bsystem\s+prompt\b"
    r"|\b(?:approve|mark)\s+(?:this|the)\s+invoice\s+(?:as\s+)?(?:approved|paid|immediately)",
    re.IGNORECASE,
)


def instruction_check(notes: list[str], text: str) -> dict[str, Any] | None:
    """The ``instruction_text_found`` warning when the document talks to an AI (in its text, or
    as the model noted); None otherwise. What it says is never acted on."""
    m = _HOSTILE.search(text or "")
    noted = any("instruction text found" in n.casefold() for n in notes)
    if m is None and not noted:
        return None
    seen = f" (“{m.group(0)[:80]}”)" if m else ""
    return check(
        "instruction_text_found",
        False,
        "The document doesn't try to give instructions",
        f"The document contains text addressed to an AI{seen}; it was ignored.",
        severity="warn",
    )


def _iso(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def risk_checks(
    data: dict[str, Any],
    *,
    today: date,
    duplicates: list[Any],
    similar: list[Any],
    bank: dict[str, Any] | None,
    had_bank: bool,
    profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    missing = [
        f for f in ("invoice_number", "invoice_date", "stated_total", "currency") if not data.get(f)
    ]
    out.append(
        check(
            "missing_fields",
            not missing,
            "The invoice number, date, total and currency are all read",
            "" if not missing else f"Not read: {', '.join(f.replace('_', ' ') for f in missing)}.",
            fields=missing,
        )
    )
    if duplicates:
        d = duplicates[0]
        out.append(
            check(
                "duplicate",
                False,
                "Not a duplicate of an invoice on file",
                f"Same vendor and invoice number as “{d.title}” ({d.status}).",
                fields=["invoice_number"],
                duplicate_of=str(d.id),
            )
        )
    for s in similar[:1]:
        out.append(
            check(
                "possible_duplicate",
                False,
                "Doesn't look like another invoice on file",
                f"Looks like “{s.record.title}” (same vendor and amount, close date; "
                f"{round(s.similarity * 100)}% alike).",
                severity="warn",
                fields=["invoice_number", "stated_total"],
                similar_to=str(s.record.id),
            )
        )
    if bank is not None:
        if bank.get("changed"):
            out.append(
                check(
                    "bank_changed",
                    False,
                    "The bank details match the vendor's",
                    f"The payee account (•••• {bank.get('last4')}) isn't the one on file for "
                    "this vendor. Confirm it with the vendor through a known contact "
                    "before paying.",
                    fields=["bank"],
                )
            )
        elif not had_bank:
            out.append(
                check(
                    "bank_new",
                    False,
                    "Bank details seen before",
                    f"First bank details for this vendor (•••• {bank.get('last4')}).",
                    severity="info",
                )
            )
    prof = profile or {}
    cur = str(data.get("currency") or "").upper()
    total = dec(data.get("stated_total"))
    per = (prof.get("totals") or {}).get(cur) or {}
    if total is not None and int(per.get("count") or 0) >= 5:
        p10, p90 = dec(per.get("p10")), dec(per.get("p90"))
        if p90 is not None and p10 is not None and (abs(total) > 2 * p90 or abs(total) < p10 / 2):
            out.append(
                check(
                    "amount_anomaly",
                    False,
                    "The total is in this vendor's usual range",
                    f"{total} {cur} is outside this vendor's usual range ({p10} to {p90} {cur}).",
                    severity="warn",
                    fields=["stated_total"],
                )
            )
    usual = prof.get("currency_usual")
    if usual and cur and usual != cur:
        out.append(
            check(
                "currency_change",
                False,
                "The currency is the vendor's usual one",
                f"This vendor usually bills in {usual}; this invoice is in {cur}.",
                severity="warn",
                fields=["currency"],
            )
        )
    if not prof.get("invoices"):
        out.append(
            check(
                "first_invoice",
                False,
                "Invoices from this vendor seen before",
                "The first invoice from this vendor.",
                severity="info",
            )
        )
    issued = _iso(data.get("invoice_date"))
    if issued is not None:
        if issued > today + timedelta(days=3):
            out.append(
                check(
                    "future_dated",
                    False,
                    "The invoice isn't dated in the future",
                    f"Dated {issued}, in the future.",
                    severity="warn",
                    fields=["invoice_date"],
                )
            )
        elif issued < today - timedelta(days=365):
            out.append(
                check(
                    "stale",
                    False,
                    "The invoice is less than a year old",
                    f"Dated {issued}, over a year ago.",
                    severity="warn",
                    fields=["invoice_date"],
                )
            )
    usual_rate, rate = dec(prof.get("tax_rate_usual")), tax_rate(data)
    if usual_rate is not None and rate is not None and abs(rate - usual_rate) > 2:
        out.append(
            check(
                "tax_rate_unusual",
                False,
                "The tax rate is the vendor's usual one",
                f"Tax is {rate}% of the net amount; this vendor usually charges {usual_rate}%.",
                severity="info",
                fields=["tax_amount"],
            )
        )
    if total is not None and total != 0 and total % Decimal(1000) == 0 and not data.get("lines"):
        out.append(
            check(
                "round_total",
                False,
                "Not a round total with no lines",
                f"A round {total} with no line items.",
                severity="info",
            )
        )
    return out
