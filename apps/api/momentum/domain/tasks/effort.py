"""S6.4.1: effort as people write it, in minutes. "90m", "3h", "1.5h", "2h30m", "3 hours",
"1d" (a working day of 8 hours), "1w" (5 working days); a bare number is hours. None when it
can't tell."""

from __future__ import annotations

import re

DAY_MINUTES = 8 * 60
UNITS = {"m": 1, "h": 60, "d": DAY_MINUTES, "w": 5 * DAY_MINUTES}
PART = re.compile(r"(\d+(?:[.,]\d+)?)\s*(minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)(?![a-z])")


def parse_effort(text: str) -> int | None:
    s = text.strip().lower()
    if not s:
        return None
    try:
        return round(float(s.replace(",", ".")) * 60)  # a bare number is hours
    except ValueError:
        pass
    parts = PART.findall(s)
    if not parts or PART.sub("", s).strip():
        return None
    return round(sum(float(n.replace(",", ".")) * UNITS[u[0]] for n, u in parts))
