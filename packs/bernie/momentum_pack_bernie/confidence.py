"""Per-field and overall confidence (spec §6.3, §9.3.15), computed from signals, never just the
model's own number. The weights are versioned: the health page compares predicted confidence with
what reviewers actually corrected, so a change of weights is a new version."""

from __future__ import annotations

import re
from typing import Any

VERSION = 1
BASE = 0.5
W_VERBATIM = 0.3  # printed in the text layer (scaled by the page's OCR confidence)
W_CONSISTENT = 0.15  # no failing check names the field
W_SKILL = 0.05  # an active skill for the vendor covers the field
W_MODEL = 0.1  # the model's self-report (small weight)
P_VISION = 0.15  # read from an image only
P_GLYPH = 0.1  # glyph-risk characters in a figure or an identifier (S/5, O/0, I/1, B/8)
P_FAILING = 0.35  # a failing blocking check names the field

KEY_FIELDS = ("invoice_number", "invoice_date", "stated_total", "currency")
UNLOCATED = ("invoice_date", "currency")
_GLYPH = re.compile(r"(?<=\d)[SOIB]|[SOIB](?=\d)")


def _failing_fields(checks: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    blocking: set[str] = set()
    any_: set[str] = set()
    for c in checks:
        if c["passed"]:
            continue
        for f in c.get("fields") or []:
            any_.add(f)
            if c["severity"] == "block":
                blocking.add(f)
    return blocking, any_


def score(
    data: dict[str, Any],
    prov: dict[str, Any],
    checks: list[dict[str, Any]],
    *,
    model_confidence: float,
    skill_fields: set[str],
) -> tuple[float, dict[str, Any]]:
    """The overall confidence (the lowest of the key fields and the line amounts) and the
    provenance with each field's confidence and its signals."""
    if (data.get("extraction") or {}).get("method") == "einvoice":
        for p in prov.values():
            p.update({"confidence": 1.0, "signals": ["einvoice"]})
        blocking, _ = _failing_fields(checks)
        return (0.5 if blocking else 1.0), prov
    blocking, failing = _failing_fields(checks)
    ext = data.get("extraction") or {}
    text_read = int(ext.get("pages") or 0) > len(ext.get("vision_pages") or [])
    fields = [f for f in KEY_FIELDS if data.get(f) not in (None, "")]
    fields += [
        f"lines[{i}].amount"
        for i, li in enumerate(data.get("lines") or [])
        if li.get("amount") is not None
    ]
    scores: list[float] = []
    for f in fields:
        p = prov.setdefault(f, {"method": "text" if text_read else "vision"})
        signals: list[str] = []
        s = BASE
        if f in UNLOCATED:  # dates and codes are printed in other forms; judged by the reading
            if text_read:
                s += W_VERBATIM * 0.8
                signals.append("text_layer")
            else:
                s -= P_VISION
                signals.append("vision_only")
        elif p.get("bbox") and p.get("method") in ("text", "ocr"):
            s += W_VERBATIM * float(p.get("confidence") or 1.0)
            signals.append("verbatim")
        else:
            s -= P_VISION
            signals.append("vision_only" if p.get("method") == "vision" else "not_found_on_page")
        if f not in failing:
            s += W_CONSISTENT
            signals.append("consistent")
        if f in blocking:
            s -= P_FAILING
            signals.append("failing_check")
        if f in skill_fields:
            s += W_SKILL
            signals.append("skill")
        value = str(_value(data, f) or "")
        if _GLYPH.search(value.upper()):
            s -= P_GLYPH
            signals.append("glyph_risk")
        s += W_MODEL * model_confidence - W_MODEL / 2
        s = round(max(0.0, min(1.0, s)), 3)
        p.update({"confidence": s, "signals": signals, "weights": VERSION})
        scores.append(s)
    return (min(scores) if scores else 0.0), prov


def _value(data: dict[str, Any], field: str) -> Any:
    m = re.fullmatch(r"lines\[(\d+)\]\.(\w+)", field)
    if m:
        lines = data.get("lines") or []
        i = int(m.group(1))
        return lines[i].get(m.group(2)) if i < len(lines) else None
    return data.get(field)
