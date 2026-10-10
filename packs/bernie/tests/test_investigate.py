"""The critic and the investigator (spec §9.3.12): a VAT row read as a line item is the notebook's
most common failure. The critic's correction is kept only when every new figure is printed on the
page; the investigator's tools read only this document, and a value no tool showed is refused in
code, whatever the model says."""

from __future__ import annotations

import json
from typing import Any

from momentum_pack_bernie import critic, extract, investigate, read
from momentum_pack_bernie.checks_math import math_checks
from momentum_pack_bernie.locate import locate
from synth import build as B

S = B.specs()
KEY = "northwind_simple"


class NoOcr:
    ocr_available = False


def setup() -> tuple[read.Reading, extract.Extracted, Any]:
    reading = read.read_pdf(NoOcr(), B.pdf(S[KEY]), use_ocr=False)
    wrong = extract.Extracted.model_validate(B.wrong(S[KEY]))

    def recheck(ex: extract.Extracted) -> list[dict[str, Any]]:
        data = extract.to_record(
            ex,
            method="text",
            reading=reading,
            chunk_count=1,
            vendor_entity_id=None,
            vendor_name=None,
            model_alias="default",
        )
        return math_checks(data, rounding_tolerance=True) + locate(data, reading)[1]

    return reading, wrong, recheck


def blocking(checks: list[dict[str, Any]]) -> list[str]:
    return [c["id"] for c in checks if not c["passed"] and c["severity"] == "block"]


def test_the_vat_row_fails_the_checks() -> None:
    _reading, wrong, recheck = setup()
    assert "total" in blocking(recheck(wrong))


def test_a_critic_correction_that_removes_the_vat_row_is_kept() -> None:
    reading, wrong, recheck = setup()
    lines = [li.model_dump() for li in wrong.line_items[:-1]]
    res = critic.CriticResult(
        root_cause="tax_row_in_line_items",
        diagnosis="The VAT row was filed as a line.",
        corrected_fields={"line_items": lines},
        confidence=0.9,
    )
    fixed = critic.apply(wrong, res)
    assert fixed is not None and len(fixed.line_items) == len(wrong.line_items) - 1
    assert critic.grounded(wrong, fixed, reading) == (True, [])
    assert blocking(recheck(fixed)) == []


def test_a_critic_figure_not_printed_on_the_page_is_refused() -> None:
    reading, wrong, _ = setup()
    res = critic.CriticResult(corrected_fields={"stated_total": "98765.43"})
    fixed = critic.apply(wrong, res)
    assert fixed is not None
    ok, missing = critic.grounded(wrong, fixed, reading)
    assert not ok and missing == ["98765.43"]


def test_a_critic_that_gives_up_changes_nothing() -> None:
    _reading, wrong, _ = setup()
    assert critic.apply(wrong, critic.CriticResult(no_correction_possible=True)) is None
    assert critic.apply(wrong, critic.CriticResult(corrected_fields={"line_items": "x"})) is None


def test_the_critic_prompt_gets_the_exact_failing_check() -> None:
    _reading, wrong, recheck = setup()
    failing = [c for c in recheck(wrong) if not c["passed"]]
    text = critic.user_content(wrong, failing, 1, "PAGE TEXT", "")
    assert "attempt_number: 1 of 3" in text and '"id": "total"' in text
    assert "<untrusted_document>\nPAGE TEXT\n</untrusted_document>" in text


def test_the_investigator_removes_the_vat_row_and_the_checks_pass() -> None:
    reading, wrong, recheck = setup()
    inv = investigate.Investigation(reading, wrong, recheck)
    rows = json.loads(inv.run("rows", {"page": 1}))["rows"]
    assert any("VAT" in r or "Tax" in r for r in rows)
    out = json.loads(inv.run("propose_fix", {"changes": [{"remove_line": len(wrong.line_items)}]}))
    assert out["clean"] is True and out["checks_failing"] == []
    assert inv.clean and len(inv.current.line_items) == len(wrong.line_items) - 1


def test_a_value_no_tool_showed_is_refused_in_code() -> None:
    reading, wrong, recheck = setup()
    inv = investigate.Investigation(reading, wrong, recheck)
    out = json.loads(
        inv.run("propose_fix", {"changes": [{"field": "stated_total", "value": "98765.43"}]})
    )
    assert "wasn't shown by any tool" in out["rejected"]
    assert inv.current == wrong and not inv.clean
    # once a tool has shown a printed figure, it may be used
    total = B.truth(S[KEY])["stated_total"]
    inv.run("find", {"text": total})
    out = json.loads(
        inv.run("propose_fix", {"changes": [{"field": "stated_total", "value": total}]})
    )
    assert "rejected" not in out


def test_the_tools_read_only_this_document() -> None:
    reading, wrong, recheck = setup()
    inv = investigate.Investigation(reading, wrong, recheck)
    assert "error" in json.loads(inv.run("page_text", {"page": 99}))
    assert "error" in json.loads(inv.run("fetch_url", {"url": "https://example.com"}))
    assert json.loads(inv.run("sum", {"values": ["0.10", "0.20"]}))["sum"] == "0.30"
    names = {t["function"]["name"] for t in investigate.TOOLS}
    assert names == {"page_text", "rows", "find", "sum", "propose_fix"}
