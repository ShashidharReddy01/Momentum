"""S6.4.2: ✦ Suggest rebalance. The moves come from code (``domain.workload.rebalance``, a greedy
heuristic); the model writes only the headline and a short explanation, from facts computed from
those moves. Its text is kept only if every number in it appears in the facts; otherwise, or when
the gateway is down, the explanation is built in code from the same facts.

The moves are proposed as one AI action (preview → apply → one undo): a reassignment or a later
start is ``update_task``; a push is ``reschedule_task``, so dependents follow as on the timeline.
Each is previewed as the asker, so the tools' own permission checks apply again.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.ai import prompts
from momentum.ai.actions import ProposedCall, propose
from momentum.ai.context.tokens import safe
from momentum.ai.errors import AIUnavailable
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.registry import ToolRegistry
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.workload import rebalance
from momentum.domain.workload.rebalance import Rebalance, describe, hours, week, why

NUMBER = re.compile(r"\d+")


def _load(r: Rebalance, load: dict[uuid.UUID, dict[date, float]], pid: uuid.UUID, w: date) -> str:
    return f"{hours(load.get(pid, {}).get(w, 0))} of {hours(r.people[pid].capacity.get(w, 0))}"


def facts(r: Rebalance) -> list[str]:
    """What the model may use: the overloaded weeks before, each move with its reason, and the
    load afterwards. Names and titles are data (``safe``)."""
    lines = [f"Weeks: {', '.join(week(w) for w in r.weeks)}"]
    over_before = sorted(
        (
            (pid, w)
            for pid in r.people
            for w in r.weeks
            if r.before.get(pid, {}).get(w, 0) > r.people[pid].capacity.get(w, 0) + 0.5
        ),
        key=lambda c: (c[1], r.people[c[0]].name),
    )
    for pid, w in over_before:
        over = r.before[pid][w] - r.people[pid].capacity.get(w, 0)
        lines.append(
            f"Before: {safe(r.people[pid].name)} had {_load(r, r.before, pid, w)} in {week(w)} "
            f"({hours(over)} over)"
        )
    for i, mv in enumerate(r.moves, 1):
        lines.append(f"Move {i}: {describe(r, mv, safe)}. Why: {why(r, mv, safe)}")
    touched = {mv.person for mv in r.moves} | {mv.to_person for mv in r.moves if mv.to_person}
    for pid in sorted((p for p in touched if p in r.people), key=lambda p: r.people[p].name):
        weeks = [w for w in r.weeks if r.before.get(pid, {}).get(w) != r.after.get(pid, {}).get(w)]
        for w in weeks:
            lines.append(
                f"After: {safe(r.people[pid].name)} has {_load(r, r.after, pid, w)} in {week(w)}"
            )
    for u in r.unresolved:
        reason = (
            "none of their work there is something the asker can edit and has an estimate"
            if u.reason == "nothing_movable"
            else "nobody who can take it has room, and no date move fits"
        )
        who = safe(r.people[u.person].name)
        lines.append(f"Still over: {who}, {hours(u.over)} over in {week(u.week)}: {reason}")
    if r.limited:
        lines.append(f"Stopped after {len(r.moves)} moves (the most suggested at once)")
    return lines


class RebalanceNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(min_length=1, max_length=140)
    summary: str = Field(default="", max_length=900)


def _grounded(note: RebalanceNote, text: str) -> bool:
    known = set(NUMBER.findall(text))
    return all(n in known for n in NUMBER.findall(f"{note.headline} {note.summary}"))


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def plain_note(r: Rebalance) -> RebalanceNote:
    """The code-built explanation."""
    reassign = sum(1 for m in r.moves if m.kind == "reassign")
    dated = len(r.moves) - reassign
    parts = []
    if reassign:
        parts.append(_count(reassign, "reassignment"))
    if dated:
        parts.append(_count(dated, "date move"))
    what = " and ".join(parts)
    if r.status == "balanced":
        headline = f"{what.capitalize()} bring everyone under capacity"
    else:
        headline = (
            f"{what.capitalize()} ease the load; {_count(len(r.unresolved), 'week')} stay over"
        )
    notes = []
    if reassign:
        notes.append(
            "Work goes first to people with room in the same weeks who can edit the project."
        )
    if any(m.kind == "start_later" for m in r.moves):
        notes.append("Where nobody had room, a task starts later and keeps its due date.")
    pushes = [m for m in r.moves if m.kind == "push"]
    if pushes:
        keys = ", ".join(m.item.key for m in pushes)
        notes.append(f"Only as a last resort, {keys} move later, which changes a due date.")
    for u in r.unresolved[:3]:
        notes.append(
            f"{r.people[u.person].name} stays {hours(u.over)} over in {week(u.week)}"
            + (
                ": nothing there you can move."
                if u.reason == "nothing_movable"
                else ": nobody with access has room."
            )
        )
    return RebalanceNote(headline=headline[:140], summary=" ".join(notes)[:900])


def empty_note(r: Rebalance) -> RebalanceNote:
    if r.status == "no_estimates":
        return RebalanceNote(
            headline="Add effort estimates first",
            summary="Rebalancing works on hours, and none of the work shown has an estimate yet.",
        )
    if r.status == "nothing_to_do":
        return RebalanceNote(
            headline="Nobody is over capacity",
            summary="Every week shown is within each person's hours.",
        )
    return RebalanceNote(headline="No move helps", summary=plain_note(r).summary)


@dataclass
class Suggestion:
    rebalance: Rebalance
    note: RebalanceNote
    ai: bool
    action_id: uuid.UUID | None


def calls_for(r: Rebalance) -> list[ProposedCall]:
    out: list[ProposedCall] = []
    for mv in r.moves:
        ref = {"id": str(mv.item.id)}
        if mv.kind == "reassign":
            assert mv.to_person is not None
            out.append(
                ProposedCall("update_task", {"task": ref, "assignee": r.people[mv.to_person].email})
            )
        elif mv.kind == "start_later":
            assert mv.new_start is not None
            out.append(
                ProposedCall("update_task", {"task": ref, "start_on": mv.new_start.isoformat()})
            )
        else:
            assert mv.new_due is not None
            args: dict[str, object] = {"task": ref, "due_on": mv.new_due.isoformat()}
            if mv.new_start is not None:
                args["start_on"] = mv.new_start.isoformat()
            args["shift_dependents"] = True
            out.append(ProposedCall("reschedule_task", args))
    return out


def _summary(r: Rebalance) -> str:
    return "Rebalance: " + "; ".join(describe(r, mv) for mv in r.moves)


async def _write_note(llm: LLM, ctx: Ctx, r: Rebalance) -> tuple[RebalanceNote, bool]:
    text = "\n".join(facts(r))
    prompt = prompts.load("workload_rebalance")
    try:
        out = await extract(
            llm,
            ctx,
            prompt=prompt,
            system=prompt.body,
            user=f'<data source="rebalance_facts">\n{text}\n</data>',
            schema=RebalanceNote,
            description="Submit the headline and explanation.",
        )
    except AIUnavailable:
        return plain_note(r), False
    if not _grounded(out, text):
        return plain_note(r), False
    return out, True


async def suggest_rebalance(
    session: AsyncSession,
    llm: LLM,
    ctx: Ctx,
    registry: ToolRegistry,
    *,
    start: date,
    weeks: int,
    project_id: uuid.UUID | None = None,
    today: date | None = None,
) -> Suggestion:
    r = await rebalance.suggest(session, ctx, start, weeks, project_id, today=today)
    if not r.moves:
        return Suggestion(r, empty_note(r), ai=False, action_id=None)
    note, ai = await _write_note(llm, ctx, r)
    proposal = await propose(
        session, ctx, registry, calls_for(r), source="inline", summary=_summary(r)
    )
    if proposal.action is None:
        detail = "; ".join(o.result.summary for _, o in proposal.failures)
        raise ValidationFailed(detail[:300] or "The rebalance couldn't be previewed")
    return Suggestion(r, note, ai, proposal.action.id)
