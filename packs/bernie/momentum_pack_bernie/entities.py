"""The vendor entity (spec §7.1, §9.8): who issues invoices, the names and tax ids they go by, the
folder names their files arrive in, and a nightly profile from their invoices (cadence, usual
currency, typical totals) that the checks and the review screen use."""

from __future__ import annotations

import itertools
import statistics
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from momentum.sdk import EntityModel, EntityType


class VendorAttributes(EntityModel):
    tax_ids: list[str] = []
    country: str | None = None
    currency_usual: str | None = None
    folder_names: list[str] = []
    bank: dict[str, Any] | None = None  # fingerprint + last4 only, set through set_bank


def _dec(v: Any) -> Decimal | None:
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except InvalidOperation:
        return None


def vendor_profile(entity: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """From the vendor's approved invoices: how many, the usual currency, totals per currency
    (median, p10, p90), the cadence in days and the last invoice date."""
    by_cur: dict[str, list[Decimal]] = {}
    dates: list[date] = []
    for r in records:
        cur = str(r.get("currency") or "").upper()
        total = _dec(r.get("stated_total"))
        if cur and total is not None:
            by_cur.setdefault(cur, []).append(total)
        try:
            if r.get("invoice_date"):
                dates.append(date.fromisoformat(str(r["invoice_date"])))
        except ValueError:
            pass
    totals = {}
    for cur, values in by_cur.items():
        v = sorted(values)
        totals[cur] = {
            "count": len(v),
            "median": str(v[len(v) // 2]),
            "p10": str(v[max(0, int(len(v) * 0.1))]),
            "p90": str(v[min(len(v) - 1, int(len(v) * 0.9))]),
        }
    dates.sort()
    gaps = [(b - a).days for a, b in itertools.pairwise(dates) if (b - a).days > 0]
    return {
        "invoices": len(records),
        "currency_usual": max(by_cur, key=lambda c: len(by_cur[c])) if by_cur else None,
        "totals": totals,
        "cadence_days": int(statistics.median(gaps)) if gaps else None,
        "last_invoice": dates[-1].isoformat() if dates else None,
    }


VENDOR = EntityType(key="vendor", model=VendorAttributes, label="Vendor", profile_fn=vendor_profile)
