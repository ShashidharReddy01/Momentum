"""E-invoices (spec §9.3.5): Factur-X embedded in a PDF and UBL 2.1 parse to the record with no
model call, amounts exactly as written."""

from __future__ import annotations

from momentum_pack_bernie import einvoice
from momentum_pack_bernie.checks_math import math_checks
from synth import build as B

S = B.specs()


def test_factur_x_embedded_in_the_pdf() -> None:
    spec = S["contoso_facturx"]
    xml = einvoice.embedded_xml(B.facturx_pdf(spec))
    assert xml is not None and einvoice.is_einvoice_xml(xml)
    data = einvoice.parse(xml)
    t = B.truth(spec)
    assert data["invoice_number"] == "CM-77015" and data["invoice_date"] == "2026-09-12"
    assert data["due_date"] == "2026-10-12" and data["currency"] == "EUR"
    assert (
        data["vendor"]["name"] == "Contoso Markets GmbH"
        and data["vendor"]["tax_id"] == "DE123456789"
    )
    assert data["stated_total"] == t["stated_total"] and data["tax_amount"] == t["tax_amount"]
    assert [li["amount"] for li in data["lines"]] == [li["amount"] for li in t["lines"]]
    assert data["_bank_account"] == "DE89370400440532013000"
    data.pop("_bank_account")
    assert [c["id"] for c in math_checks(data) if not c["passed"]] == []


def test_a_plain_pdf_has_no_embedded_invoice() -> None:
    assert einvoice.embedded_xml(B.pdf(S["northwind_simple"])) is None


def test_ubl() -> None:
    spec = S["contoso_facturx"]
    data = einvoice.parse(B.ubl_xml(spec))
    t = B.truth(spec)
    assert data["invoice_number"] == "CM-77015" and data["stated_total"] == t["stated_total"]
    assert data["lines"][0]["description"] == "Echtzeitkurse Börse Frankfurt"
    assert data["lines"][1]["quantity"] == "2" and data["lines"][1]["unit"] == "C62"


def test_hostile_xml_is_refused() -> None:
    import pytest

    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
        b"<Invoice>&b;</Invoice>"
    )
    with pytest.raises(Exception):  # noqa: B017 - defusedxml refuses entity definitions
        einvoice.parse(bomb)
