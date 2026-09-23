"""Fractional indexing for ordered lists (ADR-0007).

Keys are strings over a base-62 alphabet whose ASCII order matches the sort order, compared with
``COLLATE "C"`` in Postgres. :func:`key_between` returns a key strictly between two neighbors, so
moving an item writes only that item. Keys never end in the zero digit, which guarantees a key
between any two distinct keys exists. A small random suffix keeps concurrent inserts between the
same neighbors distinct.
"""

from __future__ import annotations

import secrets

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_INDEX = {c: i for i, c in enumerate(DIGITS)}
ZERO = DIGITS[0]
MAX_KEY_LENGTH = 32  # above this, rebalance the container


class OrderingError(ValueError):
    pass


def _validate(key: str | None) -> None:
    if key is None:
        return
    if key == "" or key.endswith(ZERO) or any(c not in _INDEX for c in key):
        raise OrderingError(f"invalid order key: {key!r}")


def _midpoint(a: str, b: str | None) -> str:
    """A key strictly between a and b (a may be '', b None means +infinity). Requires a < b."""
    if b is not None:
        n = 0
        while n < len(b) and (a[n] if n < len(a) else ZERO) == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])
    digit_a = _INDEX[a[0]] if a else 0
    digit_b = _INDEX[b[0]] if b is not None else len(DIGITS)
    if digit_b - digit_a > 1:
        return DIGITS[(digit_a + digit_b) // 2]
    if b is not None and len(b) > 1:
        return b[:1]
    return DIGITS[digit_a] + _midpoint(a[1:], None)


def key_between(a: str | None, b: str | None, *, jitter: bool = True) -> str:
    """Return a key k with a < k < b. ``None`` means the start or end of the list."""
    _validate(a)
    _validate(b)
    if a is not None and b is not None and a >= b:
        raise OrderingError(f"{a!r} must sort before {b!r}")
    lo = a or ""
    key = _midpoint(lo, b)
    if not jitter:
        return key
    suffix = "".join(secrets.choice(DIGITS[1:]) for _ in range(2))
    base = key
    # If base is a prefix of b, appending could overshoot b: move base toward a until it isn't.
    while b is not None and b.startswith(base):
        base = _midpoint(lo, base)
    return base + suffix


def keys_between(a: str | None, b: str | None, n: int) -> list[str]:
    """n increasing keys between a and b (used for bulk inserts and rebalancing)."""
    keys: list[str] = []
    prev = a
    for _ in range(n):
        prev = key_between(prev, b, jitter=False)
        keys.append(prev)
    return keys


def needs_rebalance(key: str) -> bool:
    return len(key) > MAX_KEY_LENGTH
