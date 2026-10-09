"""Extraction quality, measured (the product owner's bar: 99.99% field accuracy). Compares an
invoice record with its ground truth, field by field and line by line, and aggregates per vendor:

- **field accuracy** — header fields that match exactly (numbers as numbers: "1250.0" = "1,250.00";
  text case- and space-insensitive; dates as dates);
- **line recall / precision** — lines whose description and amount match a truth line, in order;
- **exact invoices** — every field and every line right.

Used by Bernie's evals (synthetic invoices with ground truth) and by the real-invoice benchmark
(against the COAP notebook's results, on the product owner's machine only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

HEADER = (
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "tax_amount",
    "stated_total",
    "document_type",
)
MONEY = {"subtotal", "tax_amount", "stated_total"}


def _num(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", ""))
    except InvalidOperation:
        return None


def _txt(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().casefold()


def same(field_name: str, got: Any, want: Any) -> bool:
    if field_name in MONEY or field_name in ("amount", "quantity", "unit_price"):
        a, b = _num(got), _num(want)
        return a == b
    return _txt(got) == _txt(want)


@dataclass
class Score:
    key: str
    vendor: str
    fields: dict[str, bool] = field(default_factory=dict)
    lines_expected: int = 0
    lines_found: int = 0
    lines_matched: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def exact(self) -> bool:
        return (
            all(self.fields.values())
            and self.lines_matched == self.lines_expected == self.lines_found
        )


def compare(key: str, data: dict[str, Any], truth: dict[str, Any]) -> Score:
    """`truth` holds only the fields that are printed (a field missing or None in the truth isn't
    scored); lines are matched in order on description and amount."""
    s = Score(key=key, vendor=str(truth.get("vendor") or data.get("vendor", {}).get("name") or ""))
    for f in HEADER:
        if truth.get(f) is None:
            continue
        ok = same(f, data.get(f), truth[f])
        s.fields[f] = ok
        if not ok:
            s.misses.append(f"{f}: got {data.get(f)!r}, want {truth[f]!r}")
    want = truth.get("lines") or []
    got = data.get("lines") or []
    s.lines_expected, s.lines_found = len(want), len(got)
    j = 0
    for i, w in enumerate(want):
        hit = None
        for k in range(j, len(got)):
            if same("amount", got[k].get("amount"), w.get("amount")) and _txt(
                got[k].get("description")
            ) == _txt(w.get("description")):
                hit = k
                break
        if hit is None:
            s.misses.append(f"line {i + 1}: {w.get('description')!r} {w.get('amount')} not found")
            continue
        s.lines_matched += 1
        j = hit + 1
    return s


@dataclass
class Totals:
    invoices: int
    exact: int
    field_accuracy: float
    line_recall: float
    line_precision: float
    by_vendor: dict[str, dict[str, float]]


def aggregate(scores: list[Score]) -> Totals:
    def rates(group: list[Score]) -> dict[str, float]:
        fields = [ok for s in group for ok in s.fields.values()]
        expected = sum(s.lines_expected for s in group)
        found = sum(s.lines_found for s in group)
        matched = sum(s.lines_matched for s in group)
        return {
            "invoices": float(len(group)),
            "exact": float(sum(1 for s in group if s.exact)),
            "field_accuracy": round(sum(fields) / len(fields), 6) if fields else 1.0,
            "line_recall": round(matched / expected, 6) if expected else 1.0,
            "line_precision": round(matched / found, 6) if found else 1.0,
        }

    vendors: dict[str, list[Score]] = {}
    for s in scores:
        vendors.setdefault(s.vendor, []).append(s)
    allr = rates(scores)
    return Totals(
        invoices=len(scores),
        exact=int(allr["exact"]),
        field_accuracy=allr["field_accuracy"],
        line_recall=allr["line_recall"],
        line_precision=allr["line_precision"],
        by_vendor={v: rates(g) for v, g in sorted(vendors.items())},
    )
