"""Phase 7.5 (spec §6.1): the narrative's contract. ``momentum.ai.report_narrative`` implements it
and the caller hands it in (this package never imports ``ai``). A narrator gets the builder's
facts as data and returns paragraphs; ``generate`` keeps only those that cite something."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from momentum.core.context import Ctx
from momentum.reports.document import Paragraph

# (ctx, kind, facts) -> paragraphs (each marked ai=True, with what it cites)
Narrator = Callable[[Ctx, str, dict[str, Any]], Awaitable[list[Paragraph]]]

# which paragraphs a kind's narrative has (spec §6.1)
NARRATIVE_PARTS: dict[str, tuple[str, ...]] = {
    "project_status": ("summary", "highlights", "risks", "next_steps"),
    "portfolio_status": ("summary", "highlights", "risks", "next_steps"),
    "customer_status": ("summary", "next_steps"),
    "closeout": ("went_well", "slipped", "lessons"),
}
