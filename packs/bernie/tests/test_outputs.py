"""What Bernie leaves behind (spec §9.3.15-18 and the catalogue): the task's name and fields, the
approval's text, the hold asks, the comment, the catalogue CSV in the notebook's column order, and
per-field confidence from signals."""

from __future__ import annotations

import csv
import io
from typing import Any

from momentum_pack_bernie import confidence, outputs

DATA: dict[str, Any] = {
    "document_type": "invoice",
    "vendor": {"name": "Northwind Data", "entity_id": "v1"},
    "invoice_number": "INV-2041",
    "invoice_date": "2026-10-01",
    "stated_total": "1250.00",
    "subtotal": "1041.67",
    "tax_amount": "208.33",
    "currency": "GBP",
    "lines": [
        {"n": 1, "description": "Data feed", "amount": "1000.00", "quantity": "1"},
        {"n": 2, "description": "=HYPERLINK(1)", "amount": "41.67"},
    ],
    "extraction": {"method": "text", "pages": 1, "vision_pages": []},
}
FAIL = {
    "id": "total",
    "severity": "block",
    "passed": False,
    "title": "Adds up",
    "detail": "Off by 1",
}


def test_names_and_fields() -> None:
    assert outputs.task_title(DATA) == "Northwind Data · INV-2041 · GBP 1,250.00"
    assert outputs.approval_title(DATA) == "Approve Northwind Data INV-2041 (GBP 1,250.00)"
    f = outputs.task_fields(DATA, "ready")
    assert f == {
        "Vendor": "Northwind Data",
        "Invoice #": "INV-2041",
        "Invoice date": "2026-10-01",
        "Currency": "GBP",
        "Invoice status": "Ready",
        "Amount": 1250.0,
    }
    assert outputs.task_fields({}, "hold") == {"Invoice status": "On hold"}


def test_approval_description_and_comment() -> None:
    decision = {"decision": "require_human", "reason": "Auto-approval is off.", "rule_id": "x"}
    text = outputs.approval_description(DATA, [FAIL], decision, "/records/r1")
    assert "Auto-approval is off." in text and "Off by 1" in text and "/records/r1" in text
    c = outputs.comment(DATA, [], decision, "/records/r1", status="ready", approver="Ravi")
    assert "Sent to Ravi for approval" in c and "/records/r1" in c
    allow = {"decision": "allow", "rule_id": "auto_ok", "reason": "Small and clean."}
    assert "Approved by policy (rule `auto_ok`)" in outputs.comment(
        DATA, [], allow, "/r", status="ready"
    )
    hold = {"decision": "hold", "reason": "Bank changed."}
    assert "On hold: Bank changed." in outputs.comment(DATA, [], hold, "/r", status="needs_review")


def test_hold_asks() -> None:
    bank = outputs.hold_ask(DATA, {"rule_id": "block_bank_change", "reason": "Different."})
    assert bank["title"] == "Bank details changed for Northwind Data"
    assert [o["value"] for o in bank["options"]] == [outputs.BANK_CONFIRMED, outputs.REJECT]
    assert "known contact" in bank["body"]
    dup = outputs.hold_ask(DATA, {"rule_id": "duplicate", "reason": "Same as INV41."})
    assert dup["title"].startswith("Possible duplicate") and len(dup["options"]) == 2


def test_the_catalogue_csv_keeps_the_notebook_columns() -> None:
    text, excluded = outputs.catalogue_csv(
        [
            {"file": "nw.pdf", "status": "ready", "confidence": 0.97, "data": DATA},
            {"file": "bad.pdf", "error": "unreadable"},
            {"file": "empty.pdf", "data": {**DATA, "lines": []}},
        ]
    )
    rows = list(csv.DictReader(io.StringIO(text)))
    assert list(rows[0]) == outputs.CSV_COLUMNS
    assert [r["amount"] for r in rows] == ["1000.00", "41.67"]
    assert rows[0]["vendor_name"] == "Northwind Data" and rows[0]["stated_total"] == "1250.00"
    assert rows[1]["description"] == "'=HYPERLINK(1)"  # a formula stays text
    assert excluded == [
        {"document": "bad.pdf", "reason": "unreadable"},
        {"document": "empty.pdf", "reason": "no line items"},
    ]


def test_confidence_comes_from_signals() -> None:
    prov = {
        "invoice_number": {"method": "text", "bbox": [1, 2, 3, 4], "confidence": 1.0},
        "stated_total": {"method": "text", "bbox": [1, 2, 3, 4], "confidence": 1.0},
        "lines[0].amount": {"method": "text", "bbox": [1, 2, 3, 4], "confidence": 1.0},
        "lines[1].amount": {"method": "text", "bbox": [1, 2, 3, 4], "confidence": 1.0},
    }
    overall, p = confidence.score(DATA, prov, [], model_confidence=0.97, skill_fields=set())
    assert overall >= 0.9 and p["stated_total"]["signals"] == ["verbatim", "consistent"]
    failing = [{**FAIL, "fields": ["stated_total"]}]
    low, p2 = confidence.score(DATA, prov, failing, model_confidence=0.97, skill_fields=set())
    assert low < 0.6 and "failing_check" in p2["stated_total"]["signals"]
    vision = {**DATA, "extraction": {"method": "vision", "pages": 1, "vision_pages": [1]}}
    v, _ = confidence.score(vision, {}, [], model_confidence=0.97, skill_fields=set())
    assert v < 0.85  # an image-only read always goes to a person
    glyph = {**DATA, "invoice_number": "INV-2O41"}
    _g, p3 = confidence.score(glyph, prov, [], model_confidence=0.97, skill_fields=set())
    assert "glyph_risk" in p3["invoice_number"]["signals"]
    e, _ = confidence.score(
        {**DATA, "extraction": {"method": "einvoice"}},
        {},
        [],
        model_confidence=1,
        skill_fields=set(),
    )
    assert e == 1.0
