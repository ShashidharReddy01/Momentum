"""S5.2.3 "✦ Describe what you want": a sentence or two about an agent in, a draft definition
out (name, instructions, triggers, tools, autonomy) for an admin to review, edit and save.

The model only proposes. Everything it returns is checked here against the same rules as a
hand-made agent (``AgentIn``): tools must exist and never include the forbidden ones, schedules
must be valid 5-field cron expressions, events must be ones agents can listen to, and a new agent
never starts at ``auto`` (agents.md §5). Whatever was dropped or changed is reported in ``notes``
so the admin sees it. Nothing is saved: the admin saves the (possibly edited) draft through the
normal ``POST /agents``.
"""

from __future__ import annotations

from typing import Literal

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from momentum.ai import prompts
from momentum.ai.context.tokens import safe
from momentum.ai.llm import LLM
from momentum.ai.structured import extract
from momentum.ai.tools.registry import ToolRegistry
from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.agents.schemas import FORBIDDEN_AGENT_TOOLS, AgentIn

MAX_DESCRIPTION = 2000
MAX_TOOLS = 15
# events an agent can usefully listen to (docs/architecture/realtime-jobs-events.md)
AGENT_EVENTS = (
    "task.created",
    "task.updated",
    "task.completed",
    "task.assigned",
    "task.moved",
    "task.tagged",
    "task.due_approaching",
    "comment.created",
    "project.created",
    "status_update.created",
    "approval.decided",
)


class DraftTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["schedule", "event", "assigned", "mentioned", "manual"]
    cron: str | None = Field(default=None, max_length=100)
    event: str | None = Field(default=None, max_length=60)


class AgentDraft(BaseModel):
    """What the model returns (a looser shape than ``AgentIn``; checked in ``to_agent``)."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(min_length=1, max_length=6000)
    triggers: list[DraftTrigger] = Field(default_factory=list, max_length=6)
    tools: list[str] = Field(default_factory=list, max_length=30)
    autonomy: Literal["suggest", "confirm", "auto"] = "confirm"
    model_alias: Literal["fast", "default", "smart"] = "default"


class AgentDraftOut(BaseModel):
    agent: AgentIn
    notes: list[str] = Field(default_factory=list)


def to_agent(draft: AgentDraft, registry: ToolRegistry) -> AgentDraftOut:
    """Check the model's draft against the real rules; drop or fix what doesn't fit, and say so."""
    notes: list[str] = []
    tools: list[str] = []
    for name in dict.fromkeys(draft.tools):
        if name in FORBIDDEN_AGENT_TOOLS:
            notes.append(f"Left out {name}: agents never delete or decide approvals.")
        elif registry.get(name) is None:
            notes.append(f"Left out {name}: there's no such tool.")
        else:
            tools.append(name)
    if len(tools) > MAX_TOOLS:
        notes.append(f"Kept the first {MAX_TOOLS} tools.")
        tools = tools[:MAX_TOOLS]

    triggers: list[dict[str, str]] = []
    for t in draft.triggers:
        if t.type == "schedule":
            cron = (t.cron or "").strip()
            if not croniter.is_valid(cron) or len(cron.split()) != 5:
                notes.append(f"Left out a schedule with an invalid time ({cron or 'none'}).")
                continue
            triggers.append({"type": "schedule", "cron": cron, "timezone": "workspace"})
        elif t.type == "event":
            if t.event not in AGENT_EVENTS:
                notes.append(f"Left out an event trigger on {t.event or 'nothing'}.")
                continue
            triggers.append({"type": "event", "event": t.event})
        elif not any(x["type"] == t.type for x in triggers):
            triggers.append({"type": t.type})
    if not triggers:
        triggers.append({"type": "manual"})
        notes.append('No usable trigger: added "Run now", so you can start it by hand.')

    autonomy = draft.autonomy
    if autonomy == "auto":
        autonomy = "confirm"
        notes.append("Starts at confirm: an agent earns acting alone with a track record.")
    try:
        agent = AgentIn.model_validate(
            {
                "name": draft.name,
                "description": draft.description,
                "instructions": draft.instructions,
                "triggers": triggers,
                "tools": tools,
                "autonomy": autonomy,
                "model_alias": draft.model_alias,
            }
        )
    except ValidationError as e:  # pragma: no cover - the checks above cover the known rules
        raise ValidationFailed("The draft didn't fit the agent rules; try rephrasing") from e
    return AgentDraftOut(agent=agent, notes=notes)


def _catalog(registry: ToolRegistry) -> str:
    lines = []
    for name in registry.names:
        tool = registry.get(name)
        if tool is None or name in FORBIDDEN_AGENT_TOOLS:
            continue
        kind = "read" if not tool.spec.writes else f"write, {tool.spec.risk} risk"
        lines.append(f"- {name} ({kind}): {tool.spec.description}")
    return "\n".join(lines)


async def draft_agent(
    llm: LLM, ctx: Ctx, registry: ToolRegistry, description: str
) -> AgentDraftOut:
    description = description.strip()
    if not description:
        raise ValidationFailed("Describe what the agent should do first")
    if len(description) > MAX_DESCRIPTION:
        raise ValidationFailed(f"That's too long (at most {MAX_DESCRIPTION} characters)")
    prompt = prompts.load("agent_draft")
    system = prompt.render(tools=_catalog(registry), events=", ".join(AGENT_EVENTS))
    draft = await extract(
        llm,
        ctx,
        prompt=prompt,
        system=system,
        user=f'<data source="request">{safe(description)}</data>',
        schema=AgentDraft,
        description="Submit the draft agent definition.",
    )
    return to_agent(draft, registry)
