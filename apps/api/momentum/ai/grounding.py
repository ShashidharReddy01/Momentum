"""Phase 7.5 (spec §8): keep only what Mo can back with facts.

The portfolio brief, chart explanations, handoff notes and readiness notes all send facts worked
out in code (as data, with a ``Citable:`` line) and get items back that say what they cite. An
item is kept only if it cites something that is really in the facts, and only if every number it
states appears in the facts, so Mo can be terse but never invents a name or a figure.
"""

from __future__ import annotations

import json
import re
from typing import Any

from momentum.ai.context.tokens import safe

NUMBER = re.compile(r"\d+(?:\.\d+)?")
KEY = re.compile(r"\bT-\d+\b")


def data_block(source: str, facts: Any, citable: list[str], **attrs: str) -> str:
    """The facts as a data block (never instructions), then the names an item may cite."""
    extra = "".join(f' {k}="{safe(v)}"' for k, v in attrs.items())
    return "\n".join(
        [
            f'<data source="{source}"{extra}>',
            safe(json.dumps(facts, ensure_ascii=False, default=str, indent=1)),
            "</data>",
            "Citable: " + " | ".join(safe(c) for c in citable[:80]),
        ]
    )


def match_cites(raw: list[str], citable: list[str]) -> list[str]:
    """The cites that name something in ``citable`` (case-insensitive, stored as written there).
    A cite may hold several names joined by "|" (the mock's ``{{$cites}}`` does)."""
    allowed = {c.lower(): c for c in citable}
    out: list[str] = []
    for r in raw:
        for piece in [*KEY.findall(r), *(x.strip() for x in r.split("|"))]:
            hit = allowed.get(piece.strip("[] ").lower())
            if hit and hit not in out:
                out.append(hit)
    return out


def numbers_in(facts: Any) -> set[str]:
    text = facts if isinstance(facts, str) else json.dumps(facts, default=str)
    out = set(NUMBER.findall(text))
    for n in list(out):  # 12.0 in the facts may be written 12
        if n.endswith(".0"):
            out.add(n[:-2])
    return out


def grounded(text: str, known: set[str]) -> bool:
    """Every number in ``text`` appears in the facts."""
    return all(n in known for n in NUMBER.findall(text))
