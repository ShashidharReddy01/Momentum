"""Phase 7.6 S76-05 (spec §8.6): the scrubber. Regex and checksum detectors, record values, and
fail-loud: an internal error is never "clean"."""

from __future__ import annotations

import pytest

from momentum.core import scrub as scrub_module
from momentum.sdk import scrub


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Send it to ap@acme-demo.test please", "email"),
        ("Pay GB82 WEST 1234 5698 7654 32", "iban"),
        ("Card 4111 1111 1111 1111 on file", "card"),
        ("SSN 123-45-6789", "us_ssn"),
        ("NI number AB 12 34 56 C", "uk_ni"),
        ("Call +44 20 7946 0958 today", "phone"),
        ("Reference 123456789012", "long_digits"),
    ],
)
def test_detectors(text: str, kind: str) -> None:
    result = scrub(text)
    assert not result.clean and kind in result.reasons, result.findings
    assert "[redacted]" in result.redacted


@pytest.mark.parametrize(
    "text",
    [
        "The invoice number is printed top right, under the logo.",
        "Dates are day first (DMY) on this vendor's invoices.",
        "A row labelled VAT is never a line item.",
        "Totals use a comma for decimals, e.g. 1.234,56 means one thousand.",  # a format, no value
    ],
)
def test_clean_text_passes(text: str) -> None:
    assert scrub(text).clean, scrub(text).findings


def test_checksums_avoid_false_alarms() -> None:
    # fails Luhn: not a card (a long digit run is still flagged: the scrubber errs on caution)
    assert "card" not in scrub("Card 4111 1111 1111 1112").reasons
    assert "iban" not in scrub("GB00 WEST 1234 5698 7654 32").reasons  # fails mod-97


def test_record_values() -> None:
    record = {"invoice_number": "INV-20417", "total": "1250.00", "lines": [{"amount": "830.40"}]}
    for text in (
        "The total 1,250.00 sits under the lines",
        "Look for INV-20417 in the header",
        "One line says 830.40",
    ):
        result = scrub(text, record_values=record)
        assert not result.clean and "record_value" in result.reasons, text
    assert scrub("The total sits under the lines", record_values=record).clean


def test_fail_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("detector broke")

    monkeypatch.setattr(scrub_module, "EMAIL", type("X", (), {"finditer": boom})())
    result = scrub("nothing to see")
    assert not result.clean and result.reasons == ["scrubber_error"]
