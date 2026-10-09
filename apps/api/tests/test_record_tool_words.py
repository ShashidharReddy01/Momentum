"""Phase 7.6 (found by the S76-07 live evals): Mo's record tools take the words people use. A
type by its key or label, singular or plural; a status by its key or an everyday phrase; nothing
guessed when a word fits more than one type or none."""

from __future__ import annotations

import pytest

from momentum.ai.tools.read_tools import _match_status, _match_type

TYPES = [
    {"key": "eval_bill", "label": "Bill"},
    {"key": "invoice", "label": "Supplier invoice"},
    {"key": "echo_vendor_note", "label": "Vendor note"},
]


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("eval_bill", "eval_bill"),
        ("Bill", "eval_bill"),
        ("bills", "eval_bill"),
        ("invoices", "invoice"),
        ("supplier invoice", "invoice"),
        ("vendor notes", "echo_vendor_note"),
        ("receipts", None),
    ],
)
def test_types_by_key_or_name(raw: str, key: str | None) -> None:
    assert _match_type(raw, TYPES) == key


def test_an_ambiguous_word_matches_nothing() -> None:
    both = [{"key": "a_bill", "label": "Bill"}, {"key": "b_bill", "label": "Utility bill"}]
    assert _match_type("bills", both) is None


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        ("needs_review", "needs_review"),
        ("needs review", "needs_review"),
        ("waiting for review", "needs_review"),
        ("pending", "needs_review"),
        ("Approved", "approved"),
        ("cancelled", "void"),
        ("ready to approve", "ready"),
        ("paid", None),
    ],
)
def test_statuses_by_key_or_phrase(raw: str, status: str | None) -> None:
    assert _match_status(raw) == status
