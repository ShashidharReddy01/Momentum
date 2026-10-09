"""Where values are printed (spec §9.3.10), and the rebuilt "printed on its own row" check: the
layouts the COAP notebook's check flagged wrongly (a quantity-1 line, a price under a wrapped
description, tax-inclusive line totals) pass, and a computed amount is still caught."""

from __future__ import annotations

from typing import Any

import pytest
from momentum_pack_bernie import extract, read
from momentum_pack_bernie.locate import locate, parse_number
from synth import build as B

S = B.specs()


class NoOcr:
    ocr_available = False


def record_for(
    key: str, answer: dict[str, Any] | None = None
) -> tuple[dict[str, Any], read.Reading]:
    spec = S[key]
    reading = read.read_pdf(NoOcr(), B.pdf(spec), use_ocr=False)
    ans = extract.Extracted.model_validate(answer or B.extraction_answer(spec))
    data = extract.to_record(
        ans,
        method="text",
        reading=reading,
        chunk_count=1,
        vendor_entity_id=None,
        vendor_name=None,
        model_alias="default",
    )
    return data, reading


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,250.00", "1250.00"),
        ("1.250,00", "1250.00"),
        ("$125,000.00", "125000"),
        ("(500.00)", "-500"),
        ("-500,00", "-500"),
        ("7,718.13", "7718.13"),
        ("1'234.50", "1234.5"),
    ],
)
def test_numbers_in_every_printed_form(text: str, value: str) -> None:
    from decimal import Decimal

    assert parse_number(text) == Decimal(value)


@pytest.mark.parametrize(
    "key",
    ["northwind_simple", "adatum_qty1", "litware_wrapped", "proseware_taxincl", "acme_multipage"],
)
def test_layouts_the_notebook_flagged_now_pass(key: str) -> None:
    data, reading = record_for(key)
    prov, checks = locate(data, reading)
    assert checks == []
    for i in range(len(data["lines"])):
        assert prov[f"lines[{i}].amount"]["page"] >= 1  # every amount found on its row


def test_header_boxes_pick_the_labelled_total() -> None:
    data, reading = record_for("northwind_simple")
    prov, _ = locate(data, reading)
    assert prov["invoice_number"]["page"] == 1 and len(prov["invoice_number"]["bbox"]) == 4
    total = prov["stated_total"]["bbox"]
    sub = prov["subtotal"]["bbox"]
    assert total[1] > sub[1]  # the total is printed below the subtotal


def test_a_computed_amount_is_still_caught() -> None:
    spec = S["northwind_simple"]
    ans = B.extraction_answer(spec)
    ans["line_items"][1]["amount"] = "999.99"  # not printed anywhere
    data, reading = record_for("northwind_simple", ans)
    _, checks = locate(data, reading)
    assert [c["id"] for c in checks] == ["unsourced_value"]
    assert checks[0]["fields"] == ["lines[1].amount"]


def test_a_line_whose_row_cant_be_found_is_not_flagged() -> None:
    ans = B.extraction_answer(S["northwind_simple"])
    ans["line_items"][0]["description"] = "Something not on the page at all"
    ans["line_items"][0]["amount"] = "1.11"
    data, reading = record_for("northwind_simple", ans)
    _, checks = locate(data, reading)
    assert checks == []  # no evidence either way, as in the notebook
