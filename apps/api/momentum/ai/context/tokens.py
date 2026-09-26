"""Token budgeting without a tokenizer dependency.

``estimate_tokens`` is deliberately **conservative**: about 3 characters per token (real BPE
tokenizers average ~4 for English, fewer for code, ids and non-Latin text), so a block that fits
here fits the model. Budgets are enforced by dropping or clipping the least important lines,
never by cutting a block mid-structure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

CHARS_PER_TOKEN = 3.0


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / CHARS_PER_TOKEN) + text.count("\n")


@dataclass(frozen=True)
class Block:
    """One named piece of prompt context and the budget it was built for."""

    name: str
    text: str
    budget: int

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def clip(text: str, max_tokens: int) -> str:
    """Shorten ``text`` (on a word boundary) to fit ``max_tokens``, marking the cut."""
    if estimate_tokens(text) <= max_tokens:
        return text
    limit = max(0, int((max_tokens - 1) * CHARS_PER_TOKEN) - 2)
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip() + " …"


def safe(text: str | None) -> str:
    """User or external content inside a prompt block: one line, and no ``<`` that could close
    the surrounding ``<data>``/structure tags (ai-architecture §8)."""
    if not text:
        return ""
    return " ".join(text.split()).replace("<", "&lt;").replace(">", "&gt;")


def fit(head: list[str], optional: list[str], tail: list[str], budget: int) -> list[str]:
    """``head`` and ``tail`` always stay; ``optional`` lines are kept in order until the budget
    is spent, and a note says how many were left out."""
    used = estimate_tokens("\n".join(head + tail))
    kept: list[str] = []
    for i, line in enumerate(optional):
        cost = estimate_tokens(line) + 2  # the line, its newline char and newline token
        rest = len(optional) - i
        note = estimate_tokens(f"  (+{rest} more not shown)") + 2
        if used + cost + (note if rest > 1 else 0) > budget:
            kept.append(f"  (+{rest} more not shown)")
            break
        kept.append(line)
        used += cost
    return head + kept + tail
