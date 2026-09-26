"""S3.4.4 writing help: improve, shorten, fix spelling and grammar, change tone, or translate a
piece of text the user selected in an editor (fast alias). The result is only a suggestion: the
client shows it next to the original and the user accepts or rejects it. Nothing is stored.

The text goes to the model as data (``<`` escaped, line breaks kept); the reply must be the
rewritten text only. Wrapping quotes or code fences the model adds anyway are removed, and an
empty reply is a ``bad_response`` rather than a blank suggestion.
"""

from __future__ import annotations

import re
from typing import Literal

from momentum.ai import prompts
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.core.context import Ctx

Action = Literal["improve", "shorten", "fix_grammar", "tone", "translate"]
Tone = Literal["friendly", "formal", "direct", "confident"]
MAX_CHARS = 8000

INSTRUCTIONS: dict[str, str] = {
    "improve": "Make it clearer and easier to read. Keep the length about the same.",
    "shorten": "Make it about half as long. Keep every decision, date, name and action item.",
    "fix_grammar": (
        "Fix spelling, grammar and punctuation only. Change nothing else: same words, tone "
        "and structure wherever they are already correct."
    ),
    "tone": "Rewrite it in a {tone} tone. Same content and length.",
    "translate": (
        "Translate it into {language}. Translate everything except names, links and task keys."
    ),
}
_FENCE = re.compile(r"^```[a-zA-Z]*\n(.*)\n```$", re.S)


def instruction(action: Action, *, tone: Tone | None, language: str | None) -> str:
    if action == "tone":
        return INSTRUCTIONS["tone"].format(tone=tone or "friendly")
    if action == "translate":
        if not language:
            raise ValueError("language is required to translate")
        return INSTRUCTIONS["translate"].format(language=language)
    return INSTRUCTIONS[action]


def clean(reply: str) -> str:
    text = reply.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    pairs = {'"': '"', "'": "'", "“": "”"}
    if len(text) >= 2 and pairs.get(text[0]) == text[-1]:
        text = text[1:-1].strip()
    return text


async def rewrite(
    llm: LLM,
    ctx: Ctx,
    *,
    action: Action,
    text: str,
    tone: Tone | None = None,
    language: str | None = None,
) -> str:
    prompt = prompts.load("write")
    body = text.replace("<", "&lt;").replace(">", "&gt;")
    out = await llm.complete(
        alias=prompt.alias,
        messages=[
            {
                "role": "system",
                "content": prompt.render(
                    instruction=instruction(action, tone=tone, language=language)
                ),
            },
            {"role": "user", "content": f'<data source="text">\n{body}\n</data>'},
        ],
        feature=prompt.feature,
        prompt_version=prompt.version,
        max_tokens=prompt.max_tokens,
        temperature=prompt.temperature,
        ctx=ctx,
    )
    result = clean(out.text).replace("&lt;", "<").replace("&gt;", ">")
    if not result:
        raise AIUnavailable(reason="bad_response", internal_detail="empty rewrite")
    return result
