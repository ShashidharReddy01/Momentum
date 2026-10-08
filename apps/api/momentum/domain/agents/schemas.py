"""S5.1.1: agent configuration schemas, shared by the admin API and the YAML definitions loader
(``momentum/agents/loader.py``), so an agent defined in a file and one created in the UI are
validated by exactly the same rules. See docs/ai/agents.md §1."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

Autonomy = Literal["suggest", "confirm", "auto"]
AgentKind = Literal["llm", "handler", "pack"]  # pack: Phase 7.6 (ADR-0012)
AgentAlias = Literal["fast", "default", "smart"]

KEY_PATTERN = r"^[a-z][a-z0-9_]{1,59}$"
AVATAR_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,39}$"
HANDLER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_.:-]{0,119}$"
PACK_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"  # semver major.minor.patch
EVENT_PATTERN = r"^[a-z_]+(\.[a-z_]+)+$"

# agents.md §3: agents never delete and never decide approvals. Refused on every agent, whatever
# its autonomy; the services refuse the operations too (S5.1.2), since the model is never the
# security boundary.
FORBIDDEN_AGENT_TOOLS = frozenset({"delete_task", "decide_approval"})

DEFAULT_BUDGET_USD = Decimal("5")
DEFAULT_BUDGET_TOKENS = 2_000_000  # kickoff Q4: applies while the agent's model is unpriced


def check_tools(value: list[str]) -> list[str]:
    if len(set(value)) != len(value):
        raise ValueError("tools must not repeat")
    forbidden = sorted(set(value) & FORBIDDEN_AGENT_TOOLS)
    if forbidden:
        raise ValueError(f"Agents can't use {', '.join(forbidden)}")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScheduleTrigger(_Strict):
    """``timezone``: ``workspace`` (workspaces.settings['timezone'], default UTC), ``user`` (each
    user's own timezone, for per-user agents such as Pulse) or an IANA name."""

    type: Literal["schedule"]
    cron: str = Field(max_length=100)
    timezone: str = Field(default="workspace", max_length=64)
    # S5.3.1: with ``timezone: user``, each person's own time of day replaces the cron's minute
    # and hour when they've set one (``digest_time`` = their notification digest time, "HH:MM")
    at: Literal["digest_time"] | None = None
    # S5.3.3: one run per project the agent belongs to (and may act on), for its owner
    per: Literal["project"] | None = None

    @field_validator("cron")
    @classmethod
    def _cron(cls, value: str) -> str:
        if not croniter.is_valid(value) or len(value.split()) != 5:
            raise ValueError('cron must be a 5-field cron expression, e.g. "0 15 * * FRI"')
        return value

    @model_serializer(mode="wrap")
    def _omit_unset_at(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # an unset ``at`` is left out, so schedules stored (and hashed) before it existed are
        # unchanged: installed agents don't turn "drifted" (S5.3.1)
        data: dict[str, Any] = handler(self)
        for key in ("at", "per"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _at(self) -> ScheduleTrigger:
        if self.at is not None and self.timezone != "user":
            raise ValueError("`at` needs timezone: user (it is each person's own time)")
        if self.per is not None and self.timezone == "user":
            raise ValueError("A schedule runs per person (timezone: user) or per project, not both")
        return self

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        if value in ("workspace", "user"):
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"Unknown timezone {value!r}") from e
        return value


class EventFilter(_Strict):
    project_ids: list[uuid.UUID] | None = None
    # S5.3.2: only top-level tasks (a ``task.*`` event about a subtask is skipped, before any
    # run or model call); left out when unset, so stored filters hash as before
    top_level: bool | None = None

    @model_serializer(mode="wrap")
    def _omit_unset(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if data.get("top_level") is None:
            data.pop("top_level", None)
        return data


class EventTrigger(_Strict):
    type: Literal["event"]
    event: str = Field(pattern=EVENT_PATTERN, max_length=60)
    filter: EventFilter = Field(default_factory=EventFilter)


class SimpleTrigger(_Strict):
    """Triggered by a person: a task assigned to the agent, an @mention, or "Run now"."""

    type: Literal["assigned", "mentioned", "manual"]


Trigger = Annotated[ScheduleTrigger | EventTrigger | SimpleTrigger, Field(discriminator="type")]


class AgentScope(_Strict):
    """What the agent may act on, **narrowing** what its account can see (kickoff Q1: scope never
    grants access). ``member_of`` = every project its account is a member of."""

    projects: Literal["member_of"] | list[uuid.UUID] = "member_of"
    teams: list[uuid.UUID] | None = None


class AgentLimits(_Strict):
    """Per-run limits. Null = the deployment's ceiling (``MOMENTUM_AGENT_MAX_STEPS`` /
    ``MOMENTUM_AGENT_TIMEOUT_S``); a value above the ceiling is refused."""

    max_steps: int | None = Field(default=None, ge=1)
    timeout_s: int | None = Field(default=None, ge=10)


class AgentConfig(_Strict):
    """Everything that defines an agent's behavior (a definition file minus its ``key``)."""

    name: str = Field(min_length=1, max_length=80)
    avatar: str = Field(default="teammate", pattern=AVATAR_PATTERN)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=20_000)
    kind: AgentKind = "llm"
    handler: str | None = Field(default=None, pattern=HANDLER_PATTERN)
    # Phase 7.6: set only for kind ``pack`` (installed from a pack's manifest, never typed in)
    pack_key: str | None = Field(default=None, pattern=KEY_PATTERN)
    pack_version: str | None = Field(default=None, pattern=PACK_VERSION_PATTERN)
    triggers: list[Trigger] = Field(default_factory=list, max_length=10)
    tools: list[str] = Field(default_factory=list, max_length=40)
    scope: AgentScope = Field(default_factory=AgentScope)
    autonomy: Autonomy = "confirm"
    model_alias: AgentAlias = "default"
    budget_monthly_usd: Decimal = Field(
        default=DEFAULT_BUDGET_USD, ge=0, le=10_000, decimal_places=2
    )
    budget_monthly_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS, ge=0, le=10_000_000_000)
    limits: AgentLimits = Field(default_factory=AgentLimits)

    @field_validator("name", "description", "instructions")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("tools")
    @classmethod
    def _tools(cls, value: list[str]) -> list[str]:
        return check_tools(value)

    @model_validator(mode="after")
    def _kind(self) -> AgentConfig:
        if self.kind == "handler" and not self.handler:
            raise ValueError("A handler agent needs `handler` (the registered function's name)")
        if self.kind != "handler" and self.handler is not None:
            raise ValueError("Only handler agents have a `handler`")
        if self.kind == "pack" and not (self.pack_key and self.pack_version):
            raise ValueError("A pack agent needs `pack_key` and `pack_version`")
        if self.kind != "pack" and (self.pack_key is not None or self.pack_version is not None):
            raise ValueError("Only pack agents have a `pack_key` / `pack_version`")
        return self


class AgentDefinition(AgentConfig):
    """One ``momentum/agents/definitions/*.yaml`` file (or a host's definitions directory)."""

    key: str = Field(pattern=KEY_PATTERN)


class AgentIn(AgentConfig):
    """Create a custom agent. ``key`` defaults to one derived from the name."""

    key: str | None = Field(default=None, pattern=KEY_PATTERN)


class AgentPatchIn(_Strict):
    """Edit an agent. ``kind``/``handler``/``key`` can't change: they're what the agent *is*."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    avatar: str | None = Field(default=None, pattern=AVATAR_PATTERN)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, max_length=20_000)
    triggers: list[Trigger] | None = Field(default=None, max_length=10)
    tools: list[str] | None = Field(default=None, max_length=40)
    scope: AgentScope | None = None
    autonomy: Autonomy | None = None
    model_alias: AgentAlias | None = None
    budget_monthly_usd: Decimal | None = Field(default=None, ge=0, le=10_000, decimal_places=2)
    budget_monthly_tokens: int | None = Field(default=None, ge=0, le=10_000_000_000)
    limits: AgentLimits | None = None
    enabled: bool | None = None
    expected_version: int | None = None

    @field_validator("tools")
    @classmethod
    def _tools(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else check_tools(value)

    @field_validator("name", "description", "instructions")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()


class AgentProjectIn(_Strict):
    """Give an agent access to a project (its account becomes a member, visible in Share)."""

    project_id: uuid.UUID
    role: Literal["editor", "commenter", "viewer"] = "editor"


class AgentProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    key: str
    name: str
    avatar: str
    description: str
    instructions: str
    kind: AgentKind
    handler: str | None
    pack_key: str | None = None
    pack_version: str | None = None
    triggers: list[dict[str, Any]]
    tools: list[str]
    scope: dict[str, Any]
    autonomy: Autonomy
    model_alias: AgentAlias
    budget_monthly_usd: Decimal
    budget_monthly_tokens: int
    limits: dict[str, Any]
    enabled: bool
    source: Literal["starter", "host", "custom", "pack"]
    # an installed agent an admin has edited since (a re-install won't overwrite it)
    drifted: bool = False
    version: int
    created_at: datetime
    updated_at: datetime


class AgentDetailOut(AgentOut):
    projects: list[AgentProjectOut] = Field(default_factory=list)


class InstallIn(_Strict):
    keys: list[str] | None = Field(default=None, max_length=100)
    force: bool = False


InstallOutcome = Literal["installed", "updated", "unchanged", "drifted", "forced"]


class InstallRowOut(BaseModel):
    key: str
    outcome: InstallOutcome
    agent_id: uuid.UUID


class InstallOut(BaseModel):
    results: list[InstallRowOut]


class AgentStatsOut(BaseModel):
    """S5.1.4: the track record behind the autonomy toggle, and this month's spend."""

    decided: int
    accepted: int
    acceptance_rate: float | None
    undos_14d: int
    auto_applied_7d: int
    auto_undone_7d: int
    eligible_for_auto: bool
    reasons: list[str]
    month_usd: Decimal
    month_tokens: int
    priced: bool
