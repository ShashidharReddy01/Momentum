"""Phase 7.6 S76-05 (spec §8.6): the scrubber (``momentum.sdk.scrub``). Regex and checksum
detectors, no models, for text that must not carry personal or document-specific values: emails,
phone numbers, IBANs (mod-97 checked), card numbers (Luhn), US SSNs, UK NI numbers, long digit
runs, and **the values of a given record** (any money, id or number in it).

It is **fail-loud**: an internal error reports ``clean=False`` with the error as the finding,
never "looks clean". Used for skill text (rejected when unclean), trace attributes of classified
packs, and ask excerpts in notifications.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w])\+?\(?\d{1,4}\)?[\s.-]?\d{2,4}[\s.-]\d{3,4}[\s.-]?\d{0,4}(?![\w])")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
US_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
UK_NI = re.compile(r"\b[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.I)
LONG_DIGITS = re.compile(r"\d{9,}")
NUMBERISH = re.compile(r"\d[\d,.\s]{2,}\d|\d{4,}")
REDACTED = "[redacted]"


@dataclass(frozen=True)
class Finding:
    kind: str
    text: str


@dataclass(frozen=True)
class ScrubResult:
    clean: bool
    findings: list[Finding] = field(default_factory=list)
    redacted: str = ""

    @property
    def reasons(self) -> list[str]:
        return sorted({f.kind for f in self.findings})


def _luhn(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(raw: str) -> bool:
    s = raw.replace(" ", "").upper()
    if not 15 <= len(s) <= 34:
        return False
    moved = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


def _numbers(value: Any) -> Iterable[str]:
    """Every number-like value in a record (money, ids, numbers), as plain digit strings."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _numbers(v)
    elif isinstance(value, list):
        for v in value:
            yield from _numbers(v)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, int | float | Decimal):
        yield from _norm(str(value))
    elif isinstance(value, str):
        for m in NUMBERISH.finditer(value):
            yield from _norm(m.group(0))


def _norm(text: str) -> Iterable[str]:
    """``1,250.00`` → ``1250``, ``125000`` and ``1250.00``-ish forms people would print."""
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 4:
        yield digits
    try:
        d = Decimal(text.replace(",", "").replace(" ", ""))
    except InvalidOperation:
        return
    whole = str(int(d)) if d == d.to_integral_value() else None
    if whole and len(whole) >= 4:
        yield whole


def scrub(text: str, *, record_values: Any = None) -> ScrubResult:
    """Look for personal or record-specific values in ``text``. ``record_values``: a record's data
    (or any JSON); a 4+ digit run in the text equal to one of its numbers is a finding."""
    try:
        findings: list[Finding] = []
        spans: list[tuple[int, int]] = []

        def hit(kind: str, m: re.Match[str]) -> None:
            findings.append(Finding(kind, m.group(0)))
            spans.append(m.span())

        for m in EMAIL.finditer(text):
            hit("email", m)
        for m in IBAN.finditer(text):
            if _iban_ok(m.group(0)):
                hit("iban", m)
        for m in CARD.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn(digits):
                hit("card", m)
        for m in US_SSN.finditer(text):
            hit("us_ssn", m)
        for m in UK_NI.finditer(text):
            hit("uk_ni", m)
        for m in PHONE.finditer(text):
            if len(re.sub(r"\D", "", m.group(0))) >= 9:
                hit("phone", m)
        for m in LONG_DIGITS.finditer(text):
            hit("long_digits", m)
        if record_values is not None:
            values = set(_numbers(record_values))
            for m in re.finditer(r"\d[\d,.\s]*\d|\d", text):
                for candidate in _norm(m.group(0)):
                    if candidate in values:
                        hit("record_value", m)
                        break
        redacted = text
        for start, end in sorted(set(spans), reverse=True):
            redacted = redacted[:start] + REDACTED + redacted[end:]
        return ScrubResult(clean=not findings, findings=findings, redacted=redacted)
    except Exception as e:  # fail loud: an error never passes as clean
        return ScrubResult(
            clean=False, findings=[Finding("scrubber_error", type(e).__name__)], redacted=REDACTED
        )
