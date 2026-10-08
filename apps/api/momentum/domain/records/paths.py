"""Phase 7.6 S76-04: field paths into a record's data: ``vendor.name``, ``lines[3].amount`` (one
item) and ``lines[].amount`` (every item, for display specs and queries). Paths are validated
before use: a segment is a lower-case name with an optional index."""

from __future__ import annotations

import copy
import re
from typing import Any

from momentum.core.errors import ValidationFailed

PATH = re.compile(r"^[a-z_][a-z0-9_]*(\[\d*\])?(\.[a-z_][a-z0-9_]*(\[\d*\])?)*$")
_SEG = re.compile(r"^([a-z_][a-z0-9_]*)(?:\[(\d*)\])?$")
MAX_PATH = 200


def parse(path: str) -> list[tuple[str, int | str | None]]:
    """``lines[3].amount`` → ``[("lines", 3), ("amount", None)]``; ``lines[]`` names every
    item (``("lines", "*")``)."""
    if not path or len(path) > MAX_PATH or not PATH.match(path):
        raise ValidationFailed(f"Not a field path: {path!r}")
    out: list[tuple[str, int | str | None]] = []
    for seg in path.split("."):
        m = _SEG.match(seg)
        assert m is not None
        name, index = m.group(1), m.group(2)
        out.append((name, None if index is None else "*" if index == "" else int(index)))
    return out


def get(data: Any, path: str) -> Any:
    """One value (no ``[]``); ``None`` when any step is missing."""
    cur = data
    for name, index in parse(path):
        if index == "*":
            raise ValidationFailed(f"{path!r} names many values")
        cur = cur.get(name) if isinstance(cur, dict) else None
        if index is not None:
            i = int(index)
            cur = cur[i] if isinstance(cur, list) and 0 <= i < len(cur) else None
        if cur is None:
            return None
    return cur


def get_all(data: Any, path: str) -> list[Any]:
    """Every value a path names (``lines[].amount`` → one per line), skipping missing ones."""
    found: list[Any] = [data]
    for name, index in parse(path):
        nxt: list[Any] = []
        for cur in found:
            value = cur.get(name) if isinstance(cur, dict) else None
            if index is None:
                if value is not None:
                    nxt.append(value)
            elif index == "*":
                if isinstance(value, list):
                    nxt.extend(v for v in value if v is not None)
            elif isinstance(value, list) and 0 <= int(index) < len(value):
                nxt.append(value[int(index)])
        found = nxt
    return found


def set_(data: dict[str, Any], path: str, value: Any) -> None:
    """Set one value in place. Objects on the way are created; list items must exist."""
    steps = parse(path)
    cur: Any = data
    for i, (name, index) in enumerate(steps):
        last = i == len(steps) - 1
        if index == "*":
            raise ValidationFailed(f"{path!r} names many values")
        if not isinstance(cur, dict):
            raise ValidationFailed(f"{path!r}: {name} isn't inside an object")
        if index is None:
            if last:
                cur[name] = value
                return
            cur = cur.setdefault(name, {})
            continue
        items = cur.get(name)
        if not isinstance(items, list) or not 0 <= int(index) < len(items):
            raise ValidationFailed(f"{path!r}: there is no item {index} in {name}")
        if last:
            items[int(index)] = value
            return
        cur = items[int(index)]


def array(data: dict[str, Any], path: str) -> list[Any]:
    """The list a path names (for item operations), created when missing."""
    steps = parse(path)
    parent_path = ".".join(f"{n}" if i is None else f"{n}[{i}]" for n, i in steps[:-1])
    parent = get(data, parent_path) if parent_path else data
    name, index = steps[-1]
    if index is not None or not isinstance(parent, dict):
        raise ValidationFailed(f"{path!r} isn't a list")
    items = parent.setdefault(name, [])
    if not isinstance(items, list):
        raise ValidationFailed(f"{path!r} isn't a list")
    return items


def clone(data: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(data)
