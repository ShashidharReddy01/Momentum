"""Phase 7.5 S75-02 (spec §4.2, §11.2): every format → the expected DocumentModel parts."""

from __future__ import annotations

import pytest

from momentum.files.model import ImageRef, TableBlock, TextBlock
from momentum.files.parse import parse_bytes
from tests.fixtures.files import build


def _parse(data: bytes, name: str, mime: str = "application/octet-stream"):  # type: ignore[no-untyped-def]
    return parse_bytes(data, name, mime)


def _texts(r) -> str:  # type: ignore[no-untyped-def]
    return "\n".join(b.text for b in r.model.blocks if isinstance(b, TextBlock))


def test_docx_outline_tables_header_footer_comment_image() -> None:
    r = _parse(build.docx_sow(), "sow.docx")
    assert r.status == "ok"
    m = r.model
    titles = [(o.title, o.level) for o in m.outline]
    assert (
        ("Scope", 1) in titles and ("Deliverables", 2) in titles and ("Out of scope", 2) in titles
    )
    out = next(o for o in m.outline if o.title == "Out of scope")
    assert out.locator == "§ Scope > Out of scope"
    table = next(b for b in m.blocks if isinstance(b, TableBlock))
    assert table.locator == "table 1"
    assert table.columns == ["Deliverable", "Owner", "Due"]
    assert table.rows[1] == ["Data migration plan", "Ravi Kumar", "2026-11-20"]
    text = _texts(r)
    assert "Statement of work: Northwind Synthetic Ltd" in text  # header
    assert "Confidential (synthetic sample)" in text  # footer
    assert "Lena Novak: Confirm the user count" in text  # comment
    assert build.HOSTILE in text  # file content is data: kept verbatim, never acted on
    renewal = next(b for b in m.blocks if isinstance(b, TextBlock) and "renewal clause" in b.text)
    assert renewal.locator == "§ Commercials"
    assert any(isinstance(b, ImageRef) for b in m.blocks)


def test_docm_macros_are_read_as_text_with_flags() -> None:
    r = _parse(build.docm_with_macro(), "notes.docm")
    assert r.status == "ok" and r.model.macros.present
    module = r.model.macros.modules[0]
    assert module.name == "NewMacros" and "Shell" in module.code
    assert "Attribute VB_" not in module.code
    meanings = {f.meaning for f in r.model.macros.flags}
    assert "Runs automatically when the file is opened or closed" in meanings
    assert "Runs other programs or commands" in meanings
    assert "Downloads files from the internet" in meanings
    assert "Kickoff call notes" in [o.title for o in r.model.outline]


def test_xlsx_sheets_types_formulas_named_ranges_merged_hidden() -> None:
    r = _parse(build.xlsx_invoices(200), "invoices.xlsx")
    assert r.status == "ok"
    inv, summary, notes = r.model.sheets
    assert inv.name == "Invoices" and inv.header_row_guess == 1 and inv.row_count == 200
    assert [(c.name, c.inferred_type) for c in inv.columns] == [
        ("Invoice", "text"),
        ("Customer", "text"),
        ("Amount", "number"),
        ("Status", "text"),
        ("Due", "date"),
    ]
    assert any(n.startswith("Amounts = Invoices!$C$2:$C$201") for n in inv.named_ranges)
    assert summary.has_formulas and summary.merged_cells == 1
    total = next(f for f in summary.formulas if f.cell == "B3")
    assert total.formula == "=SUM(Invoices!C2:C201)"
    data = build.invoice_rows(200)
    assert total.cached == pytest.approx(round(sum(x[2] for x in data), 2))
    rows = r.rows[summary.data_ref]
    assert rows[0][:3] == ["Invoice summary (synthetic)"] * 3  # merged range flattened
    assert notes.hidden and "Some sheets are hidden" in r.model.file.warnings
    assert r.rows[inv.data_ref][1][4] == "2026-01-05"  # dates as ISO text


def test_a_workbook_never_recalculated_says_so() -> None:
    r = _parse(build.xlsx_invoices(10, cached=False), "fresh.xlsx")
    summary = r.model.sheets[1]
    assert summary.formulas_without_values == 3
    assert all(f.cached is None for f in summary.formulas)
    assert any("never recalculated" in w for w in r.model.file.warnings)


def test_xlsm_macros_and_quote_formulas() -> None:
    r = _parse(build.xlsm_with_macro(), "book.xlsm")
    meanings = {f.meaning for f in r.model.macros.flags}
    assert "Hides itself or its windows" in meanings
    assert "Writes, copies or deletes files" in meanings
    q = _parse(build.xlsx_quote(), "quote.xlsx").model.sheets[0]
    assert next(f for f in q.formulas if f.cell == "D5").cached == 24000 + 3000 + 24000


def test_legacy_xls_values() -> None:
    r = _parse(build.xls_legacy(), "budget.xls", "application/vnd.ms-excel")
    assert r.status == "ok"
    sheet = r.model.sheets[0]
    assert sheet.name == "Budget" and sheet.row_count == 3
    assert r.rows[sheet.data_ref][2] == ["Services", 18500.5, "Pending"]
    assert any("values only" in w for w in r.model.file.warnings)


def test_csv_semicolons_and_locale() -> None:
    r = _parse(build.csv_semicolon(), "payments.csv", "text/csv")
    sheet = r.model.sheets[0]
    assert [c.name for c in sheet.columns] == ["Customer", "Amount", "Paid", "Note"]
    assert [c.inferred_type for c in sheet.columns][:3] == ["text", "number", "bool"]
    assert any("never run as formulas" in w for w in r.model.file.warnings)


def test_pptx_slides_tables_notes_pictures() -> None:
    r = _parse(build.pptx_kickoff(), "kickoff.pptx")
    m = r.model
    assert m.file.slides == 4
    assert [o.title for o in m.outline] == [
        "Implementation kickoff",
        "Timeline",
        "Team",
        "Next steps",
    ]
    table = next(b for b in m.blocks if isinstance(b, TableBlock))
    assert table.locator == "slide 2 table" and table.rows[-1] == ["Go-live", "2027-02-03"]
    assert any(b.locator == "slide 1 notes" for b in m.blocks if isinstance(b, TextBlock))
    assert any(isinstance(b, ImageRef) and b.slide == 3 for b in m.blocks)


def test_pdf_text_tables_and_scanned_pages() -> None:
    r = _parse(build.pdf_contract(), "contract.pdf", "application/pdf")
    assert r.model.file.pages == 2
    page1 = next(b for b in r.model.blocks if isinstance(b, TextBlock) and b.locator == "p1")
    assert "renews for 12 months" in page1.text
    table = next(b for b in r.model.blocks if isinstance(b, TableBlock))
    assert table.locator == "p2 table 1" and table.columns == ["Milestone", "Amount", "Due"]
    scanned = _parse(build.pdf_scanned(), "scan.pdf", "application/pdf")
    img = scanned.model.blocks[0]
    assert isinstance(img, ImageRef) and img.scanned and img.page == 1
    assert any("look scanned" in w for w in scanned.model.file.warnings)


def test_image_text_email_archive() -> None:
    img = _parse(build.png_screenshot(), "shot.png", "image/png")
    assert isinstance(img.model.blocks[0], ImageRef) and img.model.blocks[0].width == 640
    md = _parse(b"# Plan\nintro\n## Risks\nlate data\n", "plan.md", "text/markdown")
    assert [(o.title, o.level, o.locator) for o in md.model.outline] == [
        ("Plan", 1, "§ Plan"),
        ("Risks", 2, "§ Plan > Risks"),
    ]
    html = _parse(b"<p>Hello</p><script>alert(1)</script><style>p{}</style>", "x.html", "text/html")
    assert _texts(html) == "Hello"
    js = _parse(b'{"a":1,"b":[2,3]}', "x.json", "application/json")
    assert '"b": [' in _texts(js)
    eml = _parse(build.eml_customer(), "mail.eml", "message/rfc822")
    assert eml.model.email is not None
    assert eml.model.email.subject == "Re: UAT dates" and eml.model.email.cc
    assert eml.model.email.attachments == [{"name": "uat-plan.txt", "size": 19}]
    assert "start UAT on 12 January" in _texts(eml)
    msg = _parse(build.msg_customer(), "mail.msg", "application/vnd.ms-outlook")
    assert msg.status == "ok", msg.error
    assert msg.model.email is not None and msg.model.email.subject == "Re: data migration"
    assert "Go-live stays 3 February" in _texts(msg)
    z = _parse(build.zip_bundle(), "bundle.zip", "application/zip")
    assert z.model.archive is not None
    assert [e.path for e in z.model.archive.entries] == ["contract/msa.pdf", "notes/readme.txt"]
    assert "aren't opened" in (z.model.archive.skipped_reason or "")
    rtf = _parse(build.rtf_note(), "req.rtf", "application/rtf")
    assert "Single sign-on" in _texts(rtf)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("old.doc", "save it as .docx"),
        ("sheet.ods", "OpenDocument spreadsheets can't be read yet"),
        ("photo.heic", "HEIC images can't be read yet"),
        ("deck.ppt", "Old .ppt presentations can't be read yet"),
        ("tool.exe", "can't be read"),
    ],
)
def test_unsupported_formats_say_what_to_do(name: str, expected: str) -> None:
    r = _parse(b"\0\1\2not really", name)
    assert r.status == "unsupported"
    assert any(expected in w for w in r.model.file.warnings)


def test_a_damaged_file_fails_with_a_warning_not_an_exception() -> None:
    r = _parse(b"PK\x03\x04garbage", "broken.xlsx")
    assert r.status == "failed"
    assert r.model.file.warnings
    r = _parse(b"%PDF-1.4 nothing", "broken.pdf", "application/pdf")
    assert r.status == "failed"
