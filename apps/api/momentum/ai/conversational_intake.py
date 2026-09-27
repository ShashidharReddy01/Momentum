"""S4.2.2 "conversational intake": a form option that asks its questions naturally in a chat
instead of a plain form. Every answer still maps to the same task fields as a classic
submission (`domain/forms/service.submit_form` does the actual creation — one write path); the
model's only job here is to decide what to say next and to keep a running best guess at the
answers, in the caller's own question ids, ready to submit once ``done``.

Stateless on the server: each turn gets the whole transcript so far and recomputes its answer,
rather than persisting an in-progress conversation. That keeps this a plain request/response
endpoint with no new table, at the cost of resending history each turn (bounded — at most
``MAX_TURNS`` short messages, S4.2.1-style limits).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.core.context import Ctx
from momentum.domain.forms import service
from momentum.domain.forms.models import Form
from momentum.domain.forms.schemas import ConversationMessage, ConverseTurnOut, PublicQuestionOut

MAX_MESSAGE = 2000


class _Turn(BaseModel):
    """What the model returns each turn; kept separate from the API's `ConverseTurnOut` (which
    has no tool-schema strictness needs) the same way `nl_rule`'s `RuleDraft` is kept separate
    from `RuleIn`."""

    model_config = ConfigDict(extra="forbid")
    message: str = Field(max_length=MAX_MESSAGE)
    done: bool = False
    answers: dict[str, str | float | bool | None] = Field(default_factory=dict)


def _question_block(questions: list[PublicQuestionOut]) -> str:
    lines = []
    for q in questions:
        bits = [f'id="{q.id}"', "required" if q.required else "optional"]
        if q.help_text:
            bits.append(f'help="{safe(q.help_text)}"')
        if q.options:
            bits.append("options: " + ", ".join(o.label for o in q.options))
        if q.people:
            bits.append("people: " + ", ".join(p.label for p in q.people))
        if q.show_if:
            bits.append(f'only if "{q.show_if.question_id}" == "{q.show_if.equals}"')
        lines.append(f"- {safe(q.label)} ({', '.join(bits)})")
    return "\n".join(lines)


def _history_block(history: list[ConversationMessage]) -> str:
    speaker = {"assistant": "mo", "user": "person"}
    if not history:
        return "(nothing said yet — greet them and ask the first question)"
    return "\n".join(f"{speaker[m.role]}: {safe(m.text)}" for m in history)


async def converse(
    session: AsyncSession, llm: LLM, ctx: Ctx, form: Form, history: list[ConversationMessage]
) -> ConverseTurnOut:
    view = await service.public_form_view(session, form)
    prompt = prompts.load("conversational_intake")
    user = (
        f'<data source="form">\n'
        f"Title: {safe(view.name)}\n"
        f"Description: {safe(view.description or '')}\n"
        f"Questions:\n{_question_block(view.questions)}\n"
        f"</data>\n"
        f'<data source="conversation">\n{_history_block(history)}\n</data>'
    )
    turn = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=prompt.body,
        user=user,
        schema=_Turn,
        description="Say what to ask or confirm next, and the answers gathered so far.",
    )
    return ConverseTurnOut(message=turn.message, done=turn.done, answers=dict(turn.answers))
