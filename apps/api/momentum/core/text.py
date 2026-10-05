"""Text hygiene for anything that reaches Postgres.

Postgres refuses the NUL character (``\u0000``) in ``text`` and ``jsonb``. It isn't something a
person types, but it does arrive: text pasted from PDFs and Word documents, imported data, and
model output. ``strip_nul`` removes it from a string or from every string inside a JSON-like value
(dict keys included), so that input is stored as the person meant it instead of failing with a 500.
"""

from __future__ import annotations

from typing import Any

NUL = "\x00"


def strip_nul(value: Any) -> Any:
    """``value`` with every NUL removed from every string in it (dicts, lists and tuples walked)."""
    if isinstance(value, str):
        return value.replace(NUL, "") if NUL in value else value
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_nul(v) for v in value]
    if isinstance(value, tuple):
        return tuple(strip_nul(v) for v in value)
    return value
