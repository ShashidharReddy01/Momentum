"""The critic (spec §9.3.12, first half), ported from the COAP notebook's `self_check.py`: a
model call that gets the EXACT failing checks (never a vague "try again") and corrects the
extraction — a tax row filed as a line, a misread figure, a missed or duplicated line — never the
arithmetic, which the deterministic checks redo after it. At most 3 attempts; a critic that gives
up, or whose correction doesn't validate, leaves the prior extraction in place.

One rule stronger than the notebook's: every figure the critic introduces (a header amount, a
line amount) must be printed on a readable page — checked in code with the page words — or the
correction is rejected (when the document is all images there are no words to check against)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from momentum_pack_bernie.extract import Extracted, _money
from momentum_pack_bernie.locate import find_amount
from momentum_pack_bernie.read import Reading

MAX_ATTEMPTS = 3
ROOT_CAUSES = (
    "tax_row_in_line_items",
    "total_or_subtotal_row_in_line_items",
    "line_amount_misread",
    "line_missed",
    "line_duplicated",
    "tax_amount_misread",
    "subtotal_misread",
    "stated_total_misread",
    "currency_inconsistent",
    "date_misread",
    "unclear",
)
_HEADER_MONEY = ("subtotal", "tax_amount", "stated_total", "amount_due", "discount", "shipping")


class CriticResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    root_cause: str = "unclear"
    diagnosis: str = ""
    corrected_fields: dict[str, Any] = {}
    no_correction_possible: bool = False
    confidence: float = 0.0


def user_content(
    prior: Extracted, failing: list[dict[str, Any]], attempt: int, document: str, hints: str
) -> str:
    payload = [
        {
            k: c.get(k)
            for k in ("id", "title", "detail", "fields", "expected", "observed", "delta")
            if c.get(k) is not None
        }
        for c in failing
    ]
    return (
        f"attempt_number: {attempt} of {MAX_ATTEMPTS}\n\n"
        f"prior_extraction:\n{json.dumps(prior.model_dump(), indent=2, default=str)}\n\n"
        f"reconciler_error:\n{json.dumps(payload, indent=2)}\n\n"
        + (hints if hints else "")
        + f"<untrusted_document>\n{document}\n</untrusted_document>"
    )


def _new_figures(prior: Extracted, corrected: Extracted) -> list[str]:
    """Money figures in the correction that weren't in the prior extraction."""
    before = (
        {_money(getattr(prior, f)) for f in _HEADER_MONEY}
        | {_money(li.amount) for li in prior.line_items}
        | {_money(li.unit_price) for li in prior.line_items}
    )
    after = [_money(getattr(corrected, f)) for f in _HEADER_MONEY] + [
        _money(li.amount) for li in corrected.line_items
    ]
    return [v for v in after if v is not None and v not in before]


def grounded(prior: Extracted, corrected: Extracted, reading: Reading) -> tuple[bool, list[str]]:
    """Whether every new figure is printed on a readable page (always true for an all-image
    document: nothing to check against)."""
    readable = [p for p in reading.pages if p.source != "vision" and p.words]
    if not readable:
        return True, []
    missing = [
        v
        for v in _new_figures(prior, corrected)
        if not any(find_amount(p, Decimal(v)) for p in readable)
    ]
    return not missing, missing


def apply(prior: Extracted, result: CriticResult) -> Extracted | None:
    """The prior extraction with the critic's corrected fields, or None when it doesn't validate."""
    if result.no_correction_possible or not result.corrected_fields:
        return None
    merged = prior.model_dump()
    for key, value in result.corrected_fields.items():
        if key in merged:
            merged[key] = value
    try:
        fixed = Extracted.model_validate(merged)
    except ValidationError:
        return None
    for i, li in enumerate(fixed.line_items, start=1):
        li.line_number = i
    return fixed
