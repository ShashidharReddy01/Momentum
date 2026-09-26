"""Structured outputs via tool calling (ai-architecture §7): the model must call a
``submit_result`` tool whose arguments are validated against a Pydantic model. On a validation
error the model gets one repair attempt with the error; then the call fails with
``AIUnavailable(reason="bad_response")`` (callers degrade gracefully)."""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.prompts import Prompt
from momentum.ai.tools.schema import args_schema
from momentum.ai.types import Msg
from momentum.core.context import Ctx

TOOL = "submit_result"


async def extract[M: BaseModel](
    llm: LLM,
    ctx: Ctx,
    *,
    prompt: Prompt,
    system: str,
    user: str,
    schema: type[M],
    description: str = "Submit the structured result.",
) -> M:
    tool = {
        "type": "function",
        "function": {"name": TOOL, "description": description, "parameters": args_schema(schema)},
    }
    messages: list[Msg] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error = ""
    for attempt in range(2):
        c = await llm.complete(
            alias=prompt.alias,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": TOOL}},
            max_tokens=prompt.max_tokens,
            temperature=prompt.temperature,
            feature=prompt.feature,
            prompt_version=prompt.version,
            ctx=ctx,
        )
        call = next((t for t in c.tool_calls if t.name == TOOL), None)
        if call is None:
            last_error = "no submit_result call"
        else:
            try:
                return schema.model_validate(call.args())
            except (ValueError, ValidationError) as e:
                last_error = str(e)[:500]
                if attempt == 0:
                    messages += [
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": call.id,
                                    "type": "function",
                                    "function": {"name": TOOL, "arguments": call.arguments},
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(
                                {
                                    "error": f"Invalid result: {last_error}. "
                                    "Call submit_result again with valid arguments."
                                }
                            ),
                        },
                    ]
                    continue
        break
    raise AIUnavailable(reason="bad_response", internal_detail=last_error)
