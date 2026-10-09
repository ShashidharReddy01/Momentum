"""Which extraction path (spec §9.3.9), the notebook's chunk merge, and the mapping to the record:
text for short readable documents, 4-page chunks for long ones (all 300 Tailspin lines), vision for
scans without OCR, mixed when only some pages are images."""

from __future__ import annotations

from momentum_pack_bernie import extract, read
from synth import build as B

S = B.specs()


class NoOcr:
    ocr_available = False


def page(n: int, source: str) -> read.Page:
    return read.Page(
        n=n,
        width=612,
        height=792,
        text="x" * 200 if source != "vision" else "",
        words=[],
        source=source,
        confidence=0.9,
    )


def test_paths() -> None:
    assert extract.plan(read.Reading(pages=[page(i, "text") for i in range(1, 9)])) == (
        "text",
        [list(range(1, 9))],
    )
    method, groups = extract.plan(read.Reading(pages=[page(i, "text") for i in range(1, 19)]))
    assert (
        method == "chunked"
        and groups[0] == [1, 2, 3, 4]
        and groups[-1] == [17, 18]
        and len(groups) == 5
    )
    assert extract.plan(read.Reading(pages=[page(1, "vision")])) == ("vision", [[1]])
    mixed = read.Reading(pages=[page(1, "text"), page(2, "vision"), page(3, "ocr")])
    assert extract.plan(mixed) == ("mixed", [[1, 2, 3]])
    big_scan = read.Reading(pages=[page(i, "vision") for i in range(1, 7)])
    assert extract.plan(big_scan) == ("vision", [[1, 2, 3, 4], [5, 6]])


def test_the_300_line_invoice_merges_to_300_lines_in_order() -> None:
    spec = S["tailspin_long"]
    reading = read.read_pdf(NoOcr(), B.pdf(spec), use_ocr=False)
    method, groups = extract.plan(reading)
    assert method == "chunked" and len(reading.pages) == 18
    parts = [extract.Extracted.model_validate(B.extraction_answer(spec, pages=g)) for g in groups]
    assert sum(len(p.line_items) for p in parts) == 300
    merged = extract.merge(parts)
    assert len(merged.line_items) == 300
    assert [li.line_number for li in merged.line_items] == list(range(1, 301))
    assert merged.line_items[0].description == "Research report #001"
    assert merged.line_items[-1].description == "Research report #300"
    # header fields printed only on the last page still arrive (last present wins)
    t = B.truth(spec)
    assert str(merged.stated_total) == t["stated_total"]
    assert merged.extraction_notes[-1].startswith("Extracted in 5 page-range chunks")


def test_the_record_keeps_numbers_exact_and_never_stores_the_bank_account() -> None:
    spec = S["northwind_simple"]
    reading = read.read_pdf(NoOcr(), B.pdf(spec), use_ocr=False)
    data = extract.to_record(
        extract.Extracted.model_validate(B.extraction_answer(spec)),
        method="text",
        reading=reading,
        chunk_count=1,
        vendor_entity_id="e1",
        vendor_name=None,
        model_alias="default",
    )
    t = B.truth(spec)
    assert data["stated_total"] == t["stated_total"] and data["tax_amount"] == t["tax_amount"]
    assert [li["amount"] for li in data["lines"]] == [li["amount"] for li in t["lines"]]
    assert data["invoice_date"] == "2026-09-03" and data["currency"] == "GBP"
    assert data["bank"] == {"last4": "5555", "bic": None}  # the full IBAN is not kept
    assert "GB33" not in str(data)
    assert data["extraction"]["method"] == "text" and data["extraction"]["text_pages"] == [1]


def test_eu_and_bracketed_numbers_map_exactly() -> None:
    assert extract._money("1.234,56") == "1234.56"
    assert extract._money("(500.00)") == "-500.00"
    assert extract._money(1250.1) == "1250.1"
    assert extract._money("€ 1 250,00") == "1250.00"
    assert extract._money("not a number") is None


def test_skills_become_the_prompt_prior() -> None:
    class Skill:
        def __init__(self, kind: str, content: dict[str, object], field: str | None = None) -> None:
            self.kind, self.content, self.field = kind, content, field

    block = extract.skills_block(
        [
            Skill(
                "hint",
                {"text": "The total is the 'Amount due this invoice' figure."},
                "stated_total",
            ),
            Skill("rule", {"date_order": "DMY"}),
            Skill("field_map", {"label": "Rechnungsbetrag", "field": "stated_total"}),
        ]
    )
    assert block.startswith("vendor skills (strong prior, not truth):")
    assert (
        "hint (stated_total)" in block
        and "date_order = DMY" in block
        and "Rechnungsbetrag" in block
    )
