"""Risk checks (spec §9.3.14): every row of the table, deterministic, and the identity rule that
catches INV-0041 vs INV41 as the same invoice."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

from momentum_pack_bernie.entities import tax_rate, vendor_profile
from momentum_pack_bernie.risk import risk_checks

from momentum.domain.records.service import normalize_identity

TODAY = date(2026, 10, 10)
DATA: dict[str, Any] = {
    "invoice_number": "INV-0041",
    "invoice_date": "2026-10-01",
    "stated_total": "1200.00",
    "subtotal": "1000.00",
    "tax_amount": "200.00",
    "currency": "GBP",
    "lines": [{"n": 1, "description": "Data feed", "amount": "1000.00"}],
}
PROFILE = {
    "invoices": 12,
    "currency_usual": "GBP",
    "totals": {"GBP": {"count": 12, "median": "1200", "p10": "1000", "p90": "1400"}},
    "tax_rate_usual": "20.00",
}


def ids(data: dict[str, Any] | None = None, **kw: Any) -> dict[str, dict[str, Any]]:
    args: dict[str, Any] = {
        "today": TODAY,
        "duplicates": [],
        "similar": [],
        "bank": None,
        "had_bank": True,
        "profile": PROFILE,
    }
    args.update(kw)
    return {c["id"]: c for c in risk_checks(data or DATA, **args)}


def failed(data: dict[str, Any] | None = None, **kw: Any) -> set[str]:
    return {k for k, c in ids(data, **kw).items() if not c["passed"]}


def test_a_usual_invoice_raises_nothing() -> None:
    assert failed() == set()


def test_inv_0041_and_inv41_are_the_same_identity() -> None:
    assert normalize_identity("INV-0041") == normalize_identity("INV41") == "inv41"
    assert normalize_identity("inv 0041") == "inv41"


def test_a_duplicate_blocks() -> None:
    dup = SimpleNamespace(id=uuid.uuid4(), title="Northwind INV41", status="approved")
    c = ids(duplicates=[dup])["duplicate"]
    assert not c["passed"] and c["severity"] == "block" and c["duplicate_of"] == str(dup.id)


def test_a_look_alike_warns() -> None:
    other = SimpleNamespace(id=uuid.uuid4(), title="Northwind INV-0042", status="ready")
    c = ids(similar=[SimpleNamespace(record=other, similarity=0.85)])["possible_duplicate"]
    assert c["severity"] == "warn" and "85%" in c["detail"]


def test_bank_changed_blocks_and_bank_new_informs() -> None:
    c = ids(bank={"changed": True, "last4": "5555", "last4_on_file": "4321"})["bank_changed"]
    assert c["severity"] == "block" and "5555" in c["detail"]
    assert "GB33" not in str(c)
    c = ids(bank={"changed": False, "last4": "5555"}, had_bank=False)["bank_new"]
    assert c["severity"] == "info"
    assert failed(bank={"changed": False, "last4": "5555"}) == set()


def test_amount_anomaly_needs_five_invoices_in_the_currency() -> None:
    big = {**DATA, "stated_total": "3000.00"}
    assert ids(big)["amount_anomaly"]["severity"] == "warn"
    small = {**DATA, "stated_total": "400.00"}
    assert "amount_anomaly" in failed(small)
    few = {**PROFILE, "totals": {"GBP": {**PROFILE["totals"]["GBP"], "count": 4}}}
    assert "amount_anomaly" not in failed(big, profile=few)


def test_currency_change_first_invoice_and_dates() -> None:
    assert "currency_change" in failed({**DATA, "currency": "EUR"})
    assert ids(profile={})["first_invoice"]["severity"] == "info"
    assert "future_dated" in failed({**DATA, "invoice_date": "2026-10-20"})
    assert "future_dated" not in failed({**DATA, "invoice_date": "2026-10-12"})
    assert "stale" in failed({**DATA, "invoice_date": "2025-09-01"})


def test_tax_rate_round_total_and_missing_fields() -> None:
    assert tax_rate(DATA) == 20
    odd = {**DATA, "tax_amount": "50.00", "stated_total": "1050.00"}
    assert ids(odd)["tax_rate_unusual"]["severity"] == "info"
    assert "round_total" in failed({**DATA, "stated_total": "5000.00", "lines": []})
    c = ids({**DATA, "invoice_number": None, "currency": ""})["missing_fields"]
    assert c["severity"] == "block" and c["fields"] == ["invoice_number", "currency"]


def test_the_vendor_profile_learns_the_usual_tax_rate() -> None:
    p = vendor_profile({}, [DATA, {**DATA, "tax_amount": "100.00"}, DATA])
    assert p["tax_rate_usual"] == "20.00" and p["currency_usual"] == "GBP"
