"""Ingest (spec §9.3.2): the COAP notebook's split rules, dedupe, limits and folder hints, plus
email attachments, images, XML, and files that can't be used (always listed, never dropped)."""

from __future__ import annotations

import io
import zipfile

import pytest
from momentum_pack_bernie import ingest
from synth import build as B

S = B.specs()


def test_three_invoices_in_one_pdf_split_into_three() -> None:
    got = ingest.ingest(
        [("acme_three.pdf", B.many([S["acme_part1"], S["acme_part2"], S["acme_part3"]]))]
    )
    assert [d.name for d in got.documents] == [
        "acme_three__part1.pdf",
        "acme_three__part2.pdf",
        "acme_three__part3.pdf",
    ]
    assert [d.page_range for d in got.documents] == [(1, 1), (2, 2), (3, 3)]
    assert all(d.parent == "acme_three.pdf" for d in got.documents)


def test_page_2_of_3_with_the_same_letterhead_is_not_split() -> None:
    got = ingest.ingest([("acme_multi.pdf", B.pdf(S["acme_multipage"]))])
    assert [(d.name, d.page_count) for d in got.documents] == [("acme_multi.pdf", 3)]


def test_boundaries_follow_the_notebooks_rules() -> None:
    pages = [
        "INVOICE Invoice Number: A-100 Bill To: X",
        "Page 2 of 2 INVOICE Invoice Number: A-100",
        "INVOICE Invoice Number: A-100 continued",  # same number: a continuation
        "INVOICE Invoice Number: B-200",  # a different number: a new invoice
        "Terms and conditions",  # no keywords: never a boundary
    ]
    assert ingest.invoice_boundaries(pages) == [0, 3]
    # no number on the first page: the first number seen belongs to it
    assert ingest.invoice_boundaries(["Cover letter", "INVOICE Invoice No: C-1"]) == [0]


def test_zip_folder_hints_dedupe_and_reasons() -> None:
    nw = B.pdf(S["northwind_simple"])
    z = B.zip_with_folders(
        {
            "Northwind Data/nw.pdf": nw,
            "Northwind Data/nw-again.pdf": nw,  # the same bytes
            "Woodgrove Terminals/inv.pdf": B.pdf(S["woodgrove_dup"]),
            "readme.txt": b"hello",
        }
    )
    got = ingest.ingest([("batch.zip", z)])
    assert [(d.name, d.vendor_hint) for d in got.documents] == [
        ("Northwind Data/nw.pdf", "northwind_data"),
        ("Woodgrove Terminals/inv.pdf", "woodgrove_terminals"),
    ]
    reasons = {s["file"]: s["reason"] for s in got.skipped}
    assert "already in this batch" in reasons["Northwind Data/nw-again.pdf"]
    assert "Not an invoice file" in reasons["readme.txt"]


def test_email_attachments_encrypted_and_empty_files() -> None:
    eml = B.eml_with({"a.pdf": B.pdf(S["acme_part1"]), "b.pdf": B.pdf(S["acme_part2"])})
    assert [d.name for d in ingest.ingest([("mail.eml", eml)]).documents] == ["a.pdf", "b.pdf"]
    enc = ingest.ingest([("locked.pdf", B.encrypted(B.pdf(S["acme_part1"])))])
    assert enc.documents == [] and "password-protected" in enc.skipped[0]["reason"]
    empty = ingest.ingest([("empty.pdf", b"")])
    assert empty.skipped == [{"file": "empty.pdf", "reason": "The file is empty"}]


def test_xml_and_images_pass_through() -> None:
    xml = B.ubl_xml(S["contoso_facturx"])
    got = ingest.ingest([("invoice.xml", xml), ("scan.png", b"\x89PNG fake")])
    assert [(d.name, d.mime) for d in got.documents] == [
        ("invoice.xml", "application/xml"),
        ("scan.png", "image/png"),
    ]


def test_zip_limits() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomb.pdf", b"0" * (5 * 1024 * 1024))  # compresses ~1000:1
    with pytest.raises(ingest.IngestError, match="zip bomb"):
        ingest.ingest([("bomb.zip", buf.getvalue())])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(ingest.MAX_ARCHIVE_ENTRIES + 1):
            z.writestr(f"f{i}.txt", b"x")
    with pytest.raises(ingest.IngestError, match="the most Bernie takes"):
        ingest.ingest([("many.zip", buf.getvalue())])
