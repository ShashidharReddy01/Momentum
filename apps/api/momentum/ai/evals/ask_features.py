"""Phase 7.6 S76-03 (spec §5.3): the eval for reading a thread reply as an ask's answer.

A case gives the question (``ask``: kind, options or form) and the person's ``reply``. Certainty
is decided in code (an exact option, yes/no, a lone number, text): those cases must not call the
model. Every other reply goes to the model, whose reading is checked against ``value`` and must
never be marked certain (it's proposed for the person to confirm).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from momentum.ai.ask_interpret import interpret_reply
from momentum.ai.llm import LLM
from momentum.core.context import Ctx
from momentum.domain.asks.models import Ask
from momentum.domain.asks.service import exact_answer

ASK_FEATURES = ("ask_interpret",)


def _ask(spec: dict[str, Any], ctx: Ctx) -> Ask:
    """A question that exists only for the eval (never saved)."""
    return Ask(
        id=uuid.uuid4(),
        workspace_id=ctx.workspace_id,
        kind=spec["kind"],
        title=spec.get("title", "A question"),
        body=spec.get("body", ""),
        options=spec.get("options"),
        form=spec.get("form"),
        status="open",
        expires_at=datetime.now(UTC),
    )


async def run_ask(llm: LLM, case: dict[str, Any], ctx: Ctx, obs: Any) -> None:
    ask = _ask(case["ask"], ctx)
    certain, value = exact_answer(ask, case["reply"])
    if certain:
        obs.data.update(ai=False, certain=True, value=value)
        return
    reading = await interpret_reply(llm, ctx, ask, case["reply"])
    obs.data.update(ai=True, certain=False, value=reading.value)
    obs.text = reading.understood
