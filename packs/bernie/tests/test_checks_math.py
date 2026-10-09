"""The arithmetic checks (spec §9.3.11), ported from the COAP notebook's `reconcile.py`, plus the
two fixes from its real batch: either tax convention, and opt-in per-line rounding."""

from __future__ import annotations

from typing import Any

from momentum_pack_bernie.checks_math import math_checks, total_check


def inv(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "currency": "USD",
        "invoice_date": "2026-09-03",
        "subtotal": "1000.00",
        "tax_amount": "200.00",
        "stated_total": "1200.00",
        "lines": [
            {"n": 1, "description": "A", "amount": "600.00"},
            {"n": 2, "description": "B", "amount": "400.00"},
        ],
    }
    base.update(over)
    return base


def failing(data: dict[str, Any], **kw: Any) -> list[str]:
    return [c["id"] for c in math_checks(data, **kw) if not c["passed"]]


def test_a_clean_invoice_passes_every_check() -> None:
    assert failing(inv()) == []


def test_a_tax_row_read_as_a_line_fails_and_says_so() -> None:
    bad = inv(lines=[*inv()["lines"], {"n": 3, "description": "VAT 20%", "amount": "200.00"}])
    c = total_check(bad)
    assert not c["passed"] and c["delta"] == "200.00"
    assert "tax row may have been read as a line item" in c["detail"]


def test_line_totals_that_include_tax_pass_when_every_figure_agrees() -> None:
    # Cboe-style: each line's printed total includes its sales tax; tax and subtotal are printed too
    gross = inv(
        subtotal="250.00",
        tax_amount="16.56",
        stated_total="266.56",
        lines=[{"n": 1, "description": "CFE Internal Distribution", "amount": "266.56"}],
    )
    c = total_check(gross)
    assert c["passed"] and c["convention"] == "gross"
    assert failing(gross) == []
    # …but not when the subtotal and tax don't add up to it
    assert failing({**gross, "subtotal": "240.00"}) == ["total", "subtotal"]


def test_rounding_is_zero_by_default_and_one_cent_per_line_when_on() -> None:
    off_by_two = inv(stated_total="1200.02")
    assert "total" in failing(off_by_two)
    assert "total" not in failing(off_by_two, rounding_tolerance=True)
    assert "total" in failing(inv(stated_total="1200.03"), rounding_tolerance=True)


def test_missing_total_missing_amounts_and_no_lines() -> None:
    assert total_check(inv(stated_total=None))["failure_class"] == "missing"
    no_amount = inv(lines=[{"n": 1, "description": "A", "amount": None}])
    assert total_check(no_amount)["detail"] == "Line(s) 1 have no amount."
    header_only = inv(lines=[])
    assert total_check(header_only)["passed"]  # subtotal + tax = total, printed
    assert not total_check(inv(lines=[], subtotal=None))["passed"]


def test_credit_notes_keep_their_signs() -> None:
    credit = inv(
        subtotal="-500.00",
        tax_amount="-100.00",
        stated_total="-600.00",
        lines=[{"n": 1, "description": "Refund", "amount": "-500.00"}],
    )
    assert failing(credit) == []


def test_dates_currency_and_numbering() -> None:
    assert "dates" in failing(inv(invoice_date="03/09/2026"))
    assert "currency" in failing(inv(currency="$"))
    assert "line_numbers" in failing(
        inv(
            lines=[
                {"n": 1, "description": "A", "amount": "600.00"},
                {"n": 3, "description": "B", "amount": "400.00"},
            ]
        )
    )
    bad_period = inv(
        lines=[
            {
                "n": 1,
                "description": "A",
                "amount": "1000.00",
                "period_start": "2026-10-01",
                "period_end": "2026-09-01",
            }
        ]
    )
    assert "period_order" in failing(bad_period)
    early_due = inv(due_date="2026-08-01")
    due = next(c for c in math_checks(early_due) if c["id"] == "due_after_issue")
    assert not due["passed"] and due["severity"] == "warn"


def test_tax_lines_and_amount_due() -> None:
    split = inv(
        tax_lines=[{"label": "VAT 20%", "amount": "150.00"}, {"label": "VAT 5%", "amount": "40.00"}]
    )
    assert "tax_lines" in failing(split)
    assert "amount_due" in failing(inv(amount_due="1300.00"))
