"""The gap ask (spec §9.3.13): one form with the four answers, valid for the asks service; each
answer becomes correction operations, a re-split or "review as extracted"."""

from __future__ import annotations

from typing import Any

from momentum_pack_bernie import ask_gap

from momentum.domain.asks.schemas import AskSpec, validate_answer

DATA: dict[str, Any] = {
    "vendor": {"name": "Northwind Data"},
    "invoice_number": "INV-2041",
    "stated_total": "1250.00",
    "currency": "GBP",
    "lines": [{"n": 1, "amount": "1000.00"}, {"n": 2, "amount": "40.00"}],
}
FAILING = [
    {
        "id": "total",
        "title": "Line items and tax add up to the total",
        "severity": "block",
        "passed": False,
        "fields": ["stated_total"],
        "expected": "1240.00",
        "observed": "1250.00",
        "delta": "-10.00",
    }
]


def spec() -> AskSpec:
    return AskSpec.model_validate(
        {
            "kind": "form",
            "title": ask_gap.title(DATA),
            "body": ask_gap.body(FAILING, ["A second look found nothing to correct."], "GBP"),
            "form": ask_gap.FORM,
            "evidence": ask_gap.evidence(
                {"stated_total": {"page": 1, "bbox": [1, 2, 3, 4]}},
                FAILING,
                "00000000-0000-0000-0000-000000000001",
            ),
            "default_on_expiry": ask_gap.DEFAULT,
        }
    )


def test_the_ask_is_a_valid_form_with_four_answers() -> None:
    s = spec()
    assert s.title == "Total doesn't add up on Northwind Data INV-2041"
    assert "printed 1250.00 GBP" in s.body and "1240.00" in s.body and "-10.00" in s.body
    assert "What I tried" in s.body
    assert s.form is not None and s.form[0].options == ask_gap.ACTIONS
    assert len(ask_gap.ACTIONS) == 4 and ask_gap.ACTIONS[0] == "Send to review as extracted"
    assert s.evidence[0].page == 1 and s.evidence[0].bbox == [1, 2, 3, 4]


def test_each_answer_becomes_operations() -> None:
    s = spec()
    form = s.form_dicts()
    total = validate_answer("form", None, form, {"action": ask_gap.TOTAL, "total": "1240.00"})
    assert ask_gap.to_ops(total, DATA) == [
        {"op": "set", "path": "stated_total", "value": "1240.00"}
    ]
    line = validate_answer(
        "form", None, form, {"action": ask_gap.LINE, "line": "2", "line_amount": "50.00"}
    )
    ops = ask_gap.to_ops(line, DATA)
    assert ops == [{"op": "set", "path": "lines[1].amount", "value": "50.00"}]
    assert ask_gap.apply_ops(DATA, ops)["lines"][1]["amount"] == "50.00"
    assert DATA["lines"][1]["amount"] == "40.00"  # a copy
    review = validate_answer("form", None, form, {"action": ask_gap.REVIEW})
    assert ask_gap.to_ops(review, DATA) == []
    assert ask_gap.to_ops({"action": ask_gap.LINE, "line": 9, "line_amount": "1"}, DATA) == []


def test_pages_for_a_re_split() -> None:
    assert ask_gap.pages("3-4", 6) == (3, 4)
    assert ask_gap.pages("pages 4 to 3", 6) == (3, 4)
    assert ask_gap.pages("5", 6) == (5, 5)
    assert ask_gap.pages("1-6", 6) is None  # the whole document isn't a split
    assert ask_gap.pages("7", 6) is None and ask_gap.pages("none", 6) is None
