"""E-invoices (spec §9.3.5): the fast path with **no model call**. A PDF/A-3 carrying Factur-X,
ZUGFeRD or XRechnung XML (UN/CEFACT CII), or a UBL 2.1 / CII XML file, is parsed deterministically
(defusedxml) into the invoice record with field confidence 1.0. Elements are matched by local name
(any namespace prefix works); amounts are kept exactly as written in the XML."""

from __future__ import annotations

import io
from datetime import date
from typing import Any

EMBEDDED_NAMES = (
    "factur-x.xml",
    "zugferd-invoice.xml",
    "zugferd_invoice.xml",
    "xrechnung.xml",
    "ZUGFeRD-invoice.xml",
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(el: Any, name: str) -> list[Any]:
    return [c for c in list(el) if _local(c.tag) == name]


def _find(el: Any, path: str) -> Any:
    cur = el
    for part in path.split("/"):
        if cur is None:
            return None
        found = _kids(cur, part)
        cur = found[0] if found else None
    return cur


def _all(el: Any, path: str) -> list[Any]:
    parts = path.split("/")
    level = [el]
    for part in parts:
        level = [k for e in level for k in _kids(e, part)]
    return level


def _text(el: Any, path: str) -> str | None:
    node = _find(el, path) if path else el
    if node is None or node.text is None:
        return None
    t = node.text.strip()
    return t or None


def _d102(value: str | None) -> str | None:
    """CII dates are format 102 (YYYYMMDD); UBL dates are ISO already."""
    if not value:
        return None
    v = value.strip()
    try:
        if len(v) == 8 and v.isdigit():
            return date(int(v[:4]), int(v[4:6]), int(v[6:8])).isoformat()
        return date.fromisoformat(v[:10]).isoformat()
    except ValueError:
        return None


def embedded_xml(pdf: bytes) -> bytes | None:
    """The e-invoice XML attached inside a PDF/A-3, if any."""
    from pypdf import PdfReader

    try:
        files = PdfReader(io.BytesIO(pdf)).attachments
    except Exception:
        return None
    by_lower = {k.lower(): v for k, v in files.items()}
    for name in EMBEDDED_NAMES:
        payload = by_lower.get(name.lower())
        if payload:
            return payload[0]
    for name, payload in by_lower.items():
        if (
            name.endswith(".xml")
            and payload
            and (b"CrossIndustryInvoice" in payload[0] or b"<Invoice" in payload[0])
        ):
            return payload[0]
    return None


def is_einvoice_xml(data: bytes) -> bool:
    head = data[:4000]
    return b"CrossIndustryInvoice" in head or b"urn:oasis:names:specification:ubl" in head


def parse(xml: bytes) -> dict[str, Any]:
    """The invoice record's data from CII or UBL XML. The bank account comes back as
    `_bank_account` for the caller to fingerprint; it's never stored."""
    from defusedxml import ElementTree

    root = ElementTree.fromstring(xml)
    kind = _local(root.tag)
    if kind == "CrossIndustryInvoice":
        return _cii(root)
    if kind in ("Invoice", "CreditNote"):
        return _ubl(root, credit=kind == "CreditNote")
    raise ValueError(f"Not an e-invoice this reader knows ({kind})")


def _cii(root: Any) -> dict[str, Any]:
    doc = _find(root, "ExchangedDocument")
    tx = _find(root, "SupplyChainTradeTransaction")
    agreement = _find(tx, "ApplicableHeaderTradeAgreement")
    settlement = _find(tx, "ApplicableHeaderTradeSettlement")
    seller = _find(agreement, "SellerTradeParty")
    totals = _find(settlement, "SpecifiedTradeSettlementHeaderMonetarySummation")
    type_code = _text(doc, "TypeCode") or "380"
    tax_ids = (
        [_text(t, "ID") for t in _all(seller, "SpecifiedTaxRegistration")]
        if seller is not None
        else []
    )
    lines = []
    for i, item in enumerate(_all(tx, "IncludedSupplyChainTradeLineItem"), start=1):
        qty_el = _find(item, "SpecifiedLineTradeDelivery/BilledQuantity")
        lines.append(
            {
                "n": i,
                "description": _text(item, "SpecifiedTradeProduct/Name") or "",
                "sku": _text(item, "SpecifiedTradeProduct/SellerAssignedID"),
                "quantity": qty_el.text.strip() if qty_el is not None and qty_el.text else None,
                "unit": qty_el.get("unitCode") if qty_el is not None else None,
                "unit_price": _text(
                    item, "SpecifiedLineTradeAgreement/NetPriceProductTradePrice/ChargeAmount"
                ),
                "amount": _text(
                    item,
                    "SpecifiedLineTradeSettlement/SpecifiedTradeSettlementLineMonetarySummation/LineTotalAmount",
                ),
                "tax_rate": _text(
                    item, "SpecifiedLineTradeSettlement/ApplicableTradeTax/RateApplicablePercent"
                ),
            }
        )
    tax_lines = (
        [
            {
                "label": (
                    f"{_text(t, 'TypeCode') or 'VAT'} {_text(t, 'RateApplicablePercent') or ''}%"
                ).strip(),
                "rate": _text(t, "RateApplicablePercent"),
                "base": _text(t, "BasisAmount"),
                "amount": _text(t, "CalculatedAmount") or "0",
            }
            for t in _kids(settlement, "ApplicableTradeTax")
        ]
        if settlement is not None
        else []
    )
    allowance = _text(totals, "AllowanceTotalAmount")
    charges = _text(totals, "ChargeTotalAmount")
    return {
        "document_type": "credit_note" if type_code in ("381", "396") else "invoice",
        "vendor": {
            "name": _text(seller, "Name") or "Unknown vendor",
            "name_as_printed": _text(seller, "Name"),
            "tax_id": next((t for t in tax_ids if t), None),
            "country": _text(seller, "PostalTradeAddress/CountryID"),
        },
        "bill_to": {"name": _text(agreement, "BuyerTradeParty/Name")},
        "invoice_number": _text(doc, "ID"),
        "po_number": _text(agreement, "BuyerOrderReferencedDocument/IssuerAssignedID"),
        "invoice_date": _d102(_text(doc, "IssueDateTime/DateTimeString")),
        "due_date": _d102(
            _text(settlement, "SpecifiedTradePaymentTerms/DueDateDateTime/DateTimeString")
        ),
        "currency": _text(settlement, "InvoiceCurrencyCode"),
        "subtotal": _text(totals, "LineTotalAmount"),
        "tax_amount": _text(totals, "TaxTotalAmount"),
        "tax_lines": tax_lines,
        "discount": allowance if allowance and allowance not in ("0", "0.00") else None,
        "shipping": charges if charges and charges not in ("0", "0.00") else None,
        "stated_total": _text(totals, "GrandTotalAmount"),
        "amount_due": _text(totals, "DuePayableAmount"),
        "lines": lines,
        "_bank_account": _text(
            settlement,
            "SpecifiedTradeSettlementPaymentMeans/PayeePartyCreditorFinancialAccount/IBANID",
        ),
    }


def _ubl(root: Any, *, credit: bool) -> dict[str, Any]:
    party = _find(root, "AccountingSupplierParty/Party")
    totals = _find(root, "LegalMonetaryTotal")
    line_tag = "CreditNoteLine" if credit else "InvoiceLine"
    qty_tag = "CreditedQuantity" if credit else "InvoicedQuantity"
    lines = []
    for i, ln in enumerate(_kids(root, line_tag), start=1):
        qty_el = _find(ln, qty_tag)
        lines.append(
            {
                "n": i,
                "description": _text(ln, "Item/Name") or _text(ln, "Item/Description") or "",
                "sku": _text(ln, "Item/SellersItemIdentification/ID"),
                "quantity": qty_el.text.strip() if qty_el is not None and qty_el.text else None,
                "unit": qty_el.get("unitCode") if qty_el is not None else None,
                "unit_price": _text(ln, "Price/PriceAmount"),
                "amount": _text(ln, "LineExtensionAmount"),
                "tax_rate": _text(ln, "Item/ClassifiedTaxCategory/Percent"),
            }
        )
    tax_total = _find(root, "TaxTotal")
    tax_lines = [
        {
            "label": f"VAT {_text(t, 'TaxCategory/Percent') or ''}%".strip(),
            "rate": _text(t, "TaxCategory/Percent"),
            "base": _text(t, "TaxableAmount"),
            "amount": _text(t, "TaxAmount") or "0",
        }
        for t in (_kids(tax_total, "TaxSubtotal") if tax_total is not None else [])
    ]
    name = _text(party, "PartyName/Name") or _text(party, "PartyLegalEntity/RegistrationName")
    allowance = _text(totals, "AllowanceTotalAmount")
    return {
        "document_type": "credit_note" if credit else "invoice",
        "vendor": {
            "name": name or "Unknown vendor",
            "name_as_printed": name,
            "tax_id": _text(party, "PartyTaxScheme/CompanyID"),
            "country": _text(party, "PostalAddress/Country/IdentificationCode"),
        },
        "bill_to": {"name": _text(root, "AccountingCustomerParty/Party/PartyName/Name")},
        "invoice_number": _text(root, "ID"),
        "po_number": _text(root, "OrderReference/ID"),
        "invoice_date": _d102(_text(root, "IssueDate")),
        "due_date": _d102(_text(root, "DueDate")),
        "currency": _text(root, "DocumentCurrencyCode"),
        "subtotal": _text(totals, "LineExtensionAmount"),
        "tax_amount": _text(tax_total, "TaxAmount") if tax_total is not None else None,
        "tax_lines": tax_lines,
        "discount": allowance if allowance and allowance not in ("0", "0.00") else None,
        "stated_total": _text(totals, "TaxInclusiveAmount"),
        "amount_due": _text(totals, "PayableAmount"),
        "lines": lines,
        "_bank_account": _text(root, "PaymentMeans/PayeeFinancialAccount/ID"),
    }
