"""Phase 7.6 S76-03 (spec §5.3): reading a thread reply as the answer to an agent's question.

Certainty is decided in code (``asks.service.exact_answer``: an exact option, yes/no, a lone
number, any text for a text ask). Everything else goes through one ``fast`` call with the ask's
shape as a closed schema (prompt ``ask_interpret/v2``, with today's date for dates without a
year, and ``no_answer`` for a reply that doesn't answer); its reading is validated in code and is
only ever **proposed**: the person confirms it with one click. It's never applied silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from momentum.ai.llm import LLM
from momentum.ai.prompts import load
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.asks.models import Ask
from momentum.domain.asks.schemas import validate_answer

FEATURE = "ask_interpret"


@dataclass(frozen=True)
class Reading:
    value: Any  # None when the reply couldn't be mapped to a valid answer
    understood: str


def _field_schema(f: dict[str, Any]) -> dict[str, Any]:
    kind = f["type"]
    if kind in ("number", "money"):
        return {"type": "number"}
    if kind == "boolean":
        return {"type": "boolean"}
    if kind == "enum":
        return {"type": "string", "enum": list(f.get("options") or [])}
    if kind == "date":
        return {"type": "string", "description": "YYYY-MM-DD"}
    return {"type": "string"}


def value_schema(ask: Ask) -> dict[str, Any]:
    """The answer's JSON schema, closed to the ask's options and fields."""
    if ask.kind in ("choice", "pick_entity", "pick_record"):
        return {"type": "string", "enum": [str(o["value"]) for o in ask.options or []]}
    if ask.kind == "confirm":
        return {"type": "boolean"}
    if ask.kind == "text":
        return {"type": "string"}
    fields = ask.form or []
    return {
        "type": "object",
        "properties": {f["name"]: _field_schema(f) for f in fields},
        "required": [f["name"] for f in fields if f.get("required", True)],
        "additionalProperties": False,
    }


def describe(ask: Ask, value: Any) -> str:
    """An answer in words ("Amount = 1250.0"), for the card's "Understood: …" line."""
    if ask.kind in ("choice", "pick_entity", "pick_record"):
        labels = {str(o["value"]): str(o["label"]) for o in ask.options or []}
        return labels.get(str(value), str(value))
    if ask.kind == "confirm":
        return "Yes" if value else "No"
    if isinstance(value, dict):
        names = {f["name"]: f["label"] for f in ask.form or []}
        return "; ".join(f"{names.get(k, k)} = {v}" for k, v in value.items() if v is not None)
    return str(value)


def _question(ask: Ask) -> str:
    shape: dict[str, Any] = {"kind": ask.kind, "title": ask.title}
    if ask.options:
        shape["options"] = [{"value": o["value"], "label": o["label"]} for o in ask.options]
    if ask.form:
        shape["fields"] = [
            {k: f[k] for k in ("name", "label", "type", "required", "options") if k in f}
            for f in ask.form
        ]
    return json.dumps(shape, ensure_ascii=False)


NO_MATCH = "I couldn't match the reply to the question; please answer on the card"


async def interpret_reply(
    llm: LLM, ctx: Ctx, ask: Ask, text: str, *, today: date | None = None
) -> Reading:
    prompt = load(FEATURE)
    if today is None:
        today = datetime.now(UTC).astimezone(ZoneInfo(ctx.actor.timezone)).date()
    tool = {
        "type": "function",
        "function": {
            "name": "answer",
            "description": "Your reading of the reply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": value_schema(ask),
                    "no_answer": {
                        "type": "boolean",
                        "description": "True when the reply doesn't answer the question",
                    },
                    "explanation": {"type": "string"},
                    "unsure": {"type": "boolean"},
                },
                "required": ["explanation"],
            },
        },
    }
    out = await llm.complete(
        alias=prompt.alias,
        feature=FEATURE,
        ctx=ctx,
        messages=[
            {"role": "system", "content": prompt.body},
            {
                "role": "user",
                "content": f'<data source="today">{today.isoformat()} ({today:%A})</data>\n'
                f'<data source="question">{_question(ask)}</data>\n'
                f'<data source="reply">{text}</data>',
            },
        ],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "answer"}},
        max_tokens=prompt.max_tokens,
        temperature=prompt.temperature,
        prompt_version=prompt.version,
    )
    try:
        args = out.tool_calls[0].args() if out.tool_calls else {}
        if args.get("no_answer") or "value" not in args:
            return Reading(None, NO_MATCH)
        value = validate_answer(ask.kind, ask.options, ask.form, args.get("value"))
    except (ValueError, ValidationFailed, IndexError):
        return Reading(None, NO_MATCH)
    return Reading(value, describe(ask, value))
