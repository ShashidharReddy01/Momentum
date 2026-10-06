"""Typed reading of spreadsheet cells (spec §4.5): locale-tolerant numbers, common date forms and
column type inference. Decisions are made per column, never per cell, so ``1.234`` means the same
thing on every row of a column."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from momentum.files.model import Cell, ColumnType

Decimal = Literal[".", ","]
DayFirst = bool

_CURRENCY = re.compile(r"[\s$€£¥₹]|USD|EUR|GBP|INR|CHF", re.IGNORECASE)
_BOOL = {"true": True, "false": False, "yes": True, "no": False}
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_DMY = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")


def _clean(text: str) -> tuple[str, bool, bool]:
    """Strip currency and spaces; report a (1,234) negative and a trailing %."""
    t = _CURRENCY.sub("", text.strip())
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    pct = t.endswith("%")
    if pct:
        t = t[:-1]
    return t, neg, pct


def decimal_vote(text: str) -> Decimal | None:
    """What this one value says about the decimal separator, if anything."""
    t, _, _ = _clean(text)
    if not re.fullmatch(r"[+-]?[\d.,]+", t):
        return None
    if "." in t and "," in t:
        return "." if t.rfind(".") > t.rfind(",") else ","
    for sep in (".", ","):
        if sep in t:
            parts = t.split(sep)
            if len(parts) > 2:  # 1.234.567 or 1,234,567: thousands, so the other is decimal
                return "," if sep == "." else "."
            if len(parts[-1]) != 3:
                return sep  # 12.5 / 12,50: a decimal
    return None


def infer_decimal(values: list[str]) -> Decimal:
    votes = [v for v in (decimal_vote(x) for x in values) if v]
    return "," if votes.count(",") > votes.count(".") else "."


def parse_number(text: str, decimal: Decimal = ".") -> float | None:
    t, neg, pct = _clean(text)
    if not t or not re.fullmatch(r"[+-]?[\d.,]*\d[\d.,]*", t):
        return None
    thousands = "," if decimal == "." else "."
    t = t.replace(thousands, "")
    if decimal == ",":
        t = t.replace(",", ".")
    try:
        n = float(t)
    except ValueError:
        return None
    if neg:
        n = -n
    return n / 100 if pct else n


def infer_day_first(values: list[str]) -> DayFirst:
    for v in values:
        m = _DMY.match(v.strip())
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > 12 >= b:
                return True
            if b > 12 >= a:
                return False
    return True


def parse_date(text: str, day_first: DayFirst = True) -> date | None:
    t = text.strip()
    m = _ISO.match(t)
    try:
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _DMY.match(t)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            d, mo = (a, b) if day_first else (b, a)
            return date(y, mo, d)
    except ValueError:
        return None
    return None


def is_empty(v: Cell) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def infer_type(values: list[Cell]) -> ColumnType:
    """A column's type from its non-empty values: ≥ 90 % numbers → number (percent when most
    carry %), ≥ 90 % dates → date, all booleans → bool, else text."""
    present = [v for v in values if not is_empty(v)]
    if not present:
        return "empty"
    if all(
        isinstance(v, bool) or (isinstance(v, str) and v.strip().lower() in _BOOL) for v in present
    ):
        return "bool"
    texts = [v for v in present if isinstance(v, str)]
    dec = infer_decimal(texts)
    numbers = sum(
        1
        for v in present
        if (isinstance(v, int | float) and not isinstance(v, bool))
        or (isinstance(v, str) and parse_number(v, dec) is not None)
    )
    if numbers >= 0.9 * len(present):
        pct = sum(1 for v in texts if v.strip().endswith("%"))
        return "percent" if pct > len(present) / 2 else "number"
    day_first = infer_day_first(texts)
    dates = sum(1 for v in texts if parse_date(v, day_first) is not None)
    if dates >= 0.9 * len(present):
        return "date"
    return "text"


def as_number(v: Cell, decimal: Decimal = ".") -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float):
        return float(v)
    return parse_number(v, decimal)


def as_date(v: Cell, day_first: DayFirst = True) -> date | None:
    if isinstance(v, str):
        return parse_date(v[:10] if _ISO.match(v[:10] or "") else v, day_first)
    return None


def as_bool(v: Cell) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return _BOOL.get(v.strip().lower())
    return None


def display(v: Cell) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return f"{v:.10g}" if v != int(v) or abs(v) >= 1e15 else str(int(v))
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)
