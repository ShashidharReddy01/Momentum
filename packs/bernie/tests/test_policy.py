"""Bernie's policy (spec §8.4): auto-approval off by default; a bank change always holds for the
stewards; a duplicate holds for the requester; even with auto-approval on, nothing that failed a
check, is new, material or uncertain is approved without a person."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from momentum_pack_bernie.checks_math import check
from momentum_pack_bernie.policy import PolicyContext, decide
from momentum_pack_bernie.settings import BernieSettings


def ctx(checks: list[dict[str, Any]] | None = None, **kw: Any) -> PolicyContext:
    args: dict[str, Any] = {
        "checks": checks or [check("total", True, "Adds up")],
        "settings": BernieSettings(),
        "vendor_is_new": False,
        "amount": Decimal("120.00"),
        "currency": "GBP",
        "confidence": 0.97,
        "vendor": "Northwind Data",
        "invoice_number": "INV-2041",
    }
    args.update(kw)
    return PolicyContext(**args)


def test_auto_approve_is_off_by_default() -> None:
    assert BernieSettings().auto_approve is False
    d = decide(ctx())
    assert (d.decision, d.rule_id, d.route) == ("require_human", "default_human", "approver")
    assert all(e["fired"] is False for e in d.evaluated)
    assert d.evaluated[0]["rule_id"] == "block_bank_change"


def test_a_bank_change_always_holds_for_the_stewards() -> None:
    bank = check("bank_changed", False, "Bank matches", "Different account")
    on = BernieSettings(auto_approve=True)
    for settings in (BernieSettings(), on):
        d = decide(ctx([bank], settings=settings, bank_last4_old="4321", bank_last4_new="5555"))
        assert (d.decision, d.route, d.rule_id) == ("hold", "stewards", "block_bank_change")
        assert "4321" in d.reason and "5555" in d.reason


def test_a_duplicate_holds_for_the_requester() -> None:
    dup = check("duplicate", False, "Not a duplicate", "Same as “Northwind INV41”.")
    d = decide(ctx([dup]))
    assert (d.decision, d.route) == ("hold", "requester") and "INV41" in d.reason


def test_auto_approve_allows_only_a_small_clean_known_invoice() -> None:
    on = BernieSettings(auto_approve=True)
    assert decide(ctx(settings=on)).decision == "allow"
    cases: list[tuple[dict[str, Any], str]] = [
        ({"checks": [check("total", False, "Adds up")]}, "not_reconciled"),
        ({"vendor_is_new": True}, "new_vendor"),
        ({"amount": Decimal("4000")}, "material"),
        ({"currency": "JPY"}, "material"),  # no limit set: always a person
        ({"amount": None}, "material"),
        ({"confidence": 0.5}, "low_confidence"),
        ({"checks": [check("amount_anomaly", False, "Usual", severity="warn")]}, "anomaly"),
        (
            {
                "checks": [
                    check("instruction_text_found", False, "No instructions", severity="warn")
                ]
            },
            "warnings",
        ),
    ]
    for change, rule in cases:
        d = decide(ctx(settings=on, **change))
        assert (d.decision, d.rule_id) == ("require_human", rule), change


def test_a_broken_rule_falls_back_to_a_person() -> None:
    class Bad:
        auto_approve = True
        materiality = "not a mapping"
        confidence_floor = 0.85

    d = decide(ctx(settings=Bad()))
    assert d.decision == "require_human"
    assert any(e.get("error") for e in d.evaluated)
