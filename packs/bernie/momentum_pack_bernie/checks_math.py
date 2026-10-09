"""Deterministic arithmetic and format checks (spec §9.3.11), ported from the COAP notebook's
`reconcile.py`: zero model calls, exact `Decimal`, every check every time. A failing `block`
check means the numbers on the record don't agree with each other.

Two improvements over the notebook, both from its own real-batch results (66/81 clean, nearly
every "needs review" a false alarm):

- **Either tax convention.** Some vendors print line totals that already include tax (Cboe: a
  "Total" column = rate + sales tax, with the tax also shown separately). The notebook only
  accepted "lines + tax = total" and flagged a correct extraction. Here the total check passes
  when the printed figures agree under either convention: lines exclude tax (Σ lines + tax +
  shipping - discount = total, and Σ lines = subtotal when a subtotal is printed) **or** lines
  include it (Σ lines = total, and subtotal + tax = total when both are printed). Nothing is
  computed into the record; this only decides whether what was transcribed is consistent.
- **Rounding.** Per-line rounding (0.01 per line) is allowed only when the vendor setting
  `rounding_tolerance` is on; the default tolerance is exactly zero, as in the notebook.

The transcription-provenance check ("is each amount printed on its own row") needs the page
words, so it lives in `locate.py`.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")
TAX_ROW = re.compile(
    r"\b(vat|tax|gst|hst|pst|mwst|ust|tva|iva|btw|moms|sales\s*tax|subtotal|total)\b|%",
    re.IGNORECASE,
)
ZERO = Decimal("0")


def dec(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None


def _iso(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def check(
    cid: str,
    passed: bool,
    title: str,
    detail: str = "",
    *,
    severity: str = "block",
    fields: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    out = {
        "id": cid,
        "severity": severity,
        "passed": passed,
        "title": title,
        "detail": detail,
        "fields": fields or [],
    }
    out.update(extra)
    return out


def _fmt(d: Decimal | None) -> str:
    return "—" if d is None else format(d, "f")


def total_check(data: dict[str, Any], tolerance_per_line: Decimal = ZERO) -> dict[str, Any]:
    lines = data.get("lines") or []
    stated = dec(data.get("stated_total"))
    if stated is None:
        return check(
            "total",
            False,
            "A total is printed and read",
            "No total was read, so the invoice can't be reconciled.",
            fields=["stated_total"],
            failure_class="missing",
        )
    tax = dec(data.get("tax_amount")) or ZERO
    shipping = dec(data.get("shipping")) or ZERO
    discount = abs(dec(data.get("discount")) or ZERO)
    subtotal = dec(data.get("subtotal"))
    amounts = [dec(li.get("amount")) for li in lines]
    tol = tolerance_per_line * max(len(lines), 1)

    def close(a: Decimal, b: Decimal) -> bool:
        return abs(a - b) <= tol

    if not lines:
        if subtotal is not None and close(subtotal + tax + shipping - discount, stated):
            return check("total", True, "Subtotal and tax add up to the total", convention="header")
        return check(
            "total",
            False,
            "Line items add up to the total",
            "No line items were read.",
            fields=["lines", "stated_total"],
            failure_class="incomplete",
        )
    if any(a is None for a in amounts):
        missing = [str(i + 1) for i, a in enumerate(amounts) if a is None]
        return check(
            "total",
            False,
            "Every line has an amount",
            f"Line(s) {', '.join(missing)} have no amount.",
            fields=["lines", "stated_total"],
            failure_class="incomplete",
        )
    line_sum = sum((a for a in amounts if a is not None), ZERO)
    # lines exclude tax (the usual convention)
    excl = close(line_sum + tax + shipping - discount, stated) and (
        subtotal is None or close(line_sum, subtotal)
    )
    if excl:
        return check("total", True, "Line items and tax add up to the total", convention="net")
    # lines already include tax (each line's printed total = net + its tax) — but never when a
    # line is really a tax or total row (the classic misread), which also makes the lines sum to
    # the total
    tax_row = any(TAX_ROW.search(str(li.get("description") or "")) for li in lines) or (
        subtotal is not None
        and tax != ZERO
        and any(a == tax for a in amounts)
        and close(line_sum - tax, subtotal)
    )
    incl = (
        not tax_row
        and dec(data.get("tax_amount")) is not None
        and close(line_sum + shipping - discount, stated)
        and (subtotal is None or close(subtotal + tax + shipping - discount, stated))
    )
    if incl:
        return check(
            "total",
            True,
            "Line items (tax included) add up to the total",
            "This vendor's line totals already include tax; the subtotal and tax agree with it.",
            convention="gross",
        )
    computed = line_sum + tax + shipping - discount
    hint = ""
    if tax_row or (subtotal is not None and close(line_sum, subtotal + tax)):
        hint = " The lines add up to subtotal + tax: a tax row may have been read as a line item."
    return check(
        "total",
        False,
        "Line items and tax add up to the total",
        f"Lines {_fmt(line_sum)} + tax {_fmt(tax)}"
        + (f" + shipping {_fmt(shipping)}" if shipping else "")
        + (f" - discount {_fmt(discount)}" if discount else "")
        + f" = {_fmt(computed)}, but the printed total is {_fmt(stated)} "
        f"(off by {_fmt(computed - stated)}).{hint}",
        fields=["lines", "tax_amount", "stated_total"],
        expected=format(computed, "f"),
        observed=format(stated, "f"),
        delta=format(computed - stated, "f"),
    )


def subtotal_check(
    data: dict[str, Any], tolerance_per_line: Decimal = ZERO
) -> dict[str, Any] | None:
    subtotal = dec(data.get("subtotal"))
    lines = data.get("lines") or []
    amounts = [dec(li.get("amount")) for li in lines]
    if subtotal is None or not lines or any(a is None for a in amounts):
        return None
    line_sum = sum((a for a in amounts if a is not None), ZERO)
    tax = dec(data.get("tax_amount")) or ZERO
    tol = tolerance_per_line * len(lines)
    ok = abs(line_sum - subtotal) <= tol or abs(line_sum - (subtotal + tax)) <= tol
    return check(
        "subtotal",
        ok,
        "Line items add up to the subtotal",
        "" if ok else f"Lines add up to {_fmt(line_sum)}, the subtotal is {_fmt(subtotal)}.",
        fields=["lines", "subtotal"],
    )


def tax_lines_check(data: dict[str, Any]) -> dict[str, Any] | None:
    tax = dec(data.get("tax_amount"))
    tlines = data.get("tax_lines") or []
    if tax is None or not tlines:
        return None
    s = sum((dec(t.get("amount")) or ZERO for t in tlines), ZERO)
    ok = s == tax
    return check(
        "tax_lines",
        ok,
        "Tax lines add up to the tax",
        "" if ok else f"Tax lines add up to {_fmt(s)}, the tax is {_fmt(tax)}.",
        fields=["tax_lines", "tax_amount"],
    )


def amount_due_check(data: dict[str, Any]) -> dict[str, Any] | None:
    due = dec(data.get("amount_due"))
    total = dec(data.get("stated_total"))
    if due is None or total is None:
        return None
    ok = abs(due) <= abs(total)
    return check(
        "amount_due",
        ok,
        "The amount due isn't more than the total",
        "" if ok else f"Amount due {_fmt(due)} is more than the total {_fmt(total)}.",
        severity="warn",
        fields=["amount_due", "stated_total"],
    )


def date_checks(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    bad = [f for f in ("invoice_date", "due_date") if data.get(f) and _iso(data.get(f)) is None]
    for i, li in enumerate(data.get("lines") or []):
        s, e = li.get("period_start"), li.get("period_end")
        if (s and _iso(s) is None) or (e and _iso(e) is None):
            bad.append(f"lines[{i}].period")
        elif s and e and _iso(s) > _iso(e):  # type: ignore[operator]
            out.append(
                check(
                    "period_order",
                    False,
                    "Each period starts before it ends",
                    f"Line {i + 1}'s period starts after it ends.",
                    fields=[f"lines[{i}].period_start", f"lines[{i}].period_end"],
                )
            )
    out.append(
        check(
            "dates",
            not bad,
            "Dates are real dates",
            "" if not bad else f"These don't read as dates: {', '.join(bad)}.",
            fields=bad,
        )
    )
    inv, due = _iso(data.get("invoice_date")), _iso(data.get("due_date"))
    if inv and due:
        out.append(
            check(
                "due_after_issue",
                due >= inv,
                "The due date isn't before the invoice date",
                "" if due >= inv else "The due date is before the invoice date.",
                severity="warn",
                fields=["due_date", "invoice_date"],
            )
        )
    return out


def currency_check(data: dict[str, Any]) -> dict[str, Any]:
    cur = data.get("currency")
    ok = bool(cur) and bool(ISO_CURRENCY.match(str(cur)))
    return check(
        "currency",
        ok,
        "The currency is a 3-letter code",
        "" if ok else f"{cur!r} isn't a 3-letter ISO currency code.",
        fields=["currency"],
    )


def line_number_check(data: dict[str, Any]) -> dict[str, Any]:
    ns = [li.get("n") for li in data.get("lines") or []]
    ok = ns == list(range(1, len(ns) + 1))
    return check(
        "line_numbers",
        ok,
        "Lines are numbered 1 to N",
        "" if ok else "Line numbers skip or repeat: a line may be missing or duplicated.",
        fields=["lines"],
    )


def math_checks(data: dict[str, Any], *, rounding_tolerance: bool = False) -> list[dict[str, Any]]:
    """Every arithmetic and format check, every time (never short-circuits)."""
    tol = Decimal("0.01") if rounding_tolerance else ZERO
    out = [total_check(data, tol)]
    for extra in (subtotal_check(data, tol), tax_lines_check(data), amount_due_check(data)):
        if extra is not None:
            out.append(extra)
    out += date_checks(data)
    out.append(currency_check(data))
    out.append(line_number_check(data))
    return out


def recheck(data: dict[str, Any]) -> list[dict[str, Any]]:
    """After a person's correction (the record type's recheck hook): the math checks again. (The
    page-based checks need the document; they run again when Bernie re-reads it.)"""
    return math_checks(data)
