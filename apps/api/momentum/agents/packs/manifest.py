"""Phase 7.6 (spec §3.2): a pack's ``manifest.yaml``, the single source for the directory, the agent
page, install, the effects policy and ``momentum packs check``.

Validated strictly (``extra="forbid"`` at every level): a typo in a manifest is a load error, not a
silently ignored key. The display fields seed the ``agents`` row at install; capabilities, effects,
data and limits are always read from here (the code), never from the row, so an admin can't widen
what an agent may do by editing it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from momentum.domain.agents.schemas import AVATAR_PATTERN, KEY_PATTERN, PACK_VERSION_PATTERN

PackKind = Literal["pipeline", "model", "script"]
Classification = Literal["public", "internal", "financial", "personal"]
PersonalData = Literal["none", "low", "high"]

# spec §8.1: the writes a pack may declare. ``job.effects.*`` refuses anything else (S76-02+).
EFFECTS_WITH_TYPES = frozenset(
    {
        "records.create",
        "records.update",
        "entities.create",
        "entities.update",
        "skills.propose",
    }
)
EFFECTS_PLAIN = frozenset(
    {
        "tasks.create_subtask",
        "tasks.set_fields",
        "tasks.rename",
        "tasks.move_to_review",
        "tasks.request_approval",
        "tasks.complete_own",
        "attachments.create",
        "comments.create",
    }
)
EFFECT_NAMES = EFFECTS_WITH_TYPES | EFFECTS_PLAIN
TRIGGER_TYPES = ("assigned", "mentioned", "manual", "plan_step", "event", "schedule")
IO_FILE_KINDS = frozenset({"pdf", "image", "zip", "xml", "email", "xlsx", "csv", "docx", "text"})

_RANGE_PART = re.compile(r"^(>=|<=|>|<|==)\s*(\d+)(?:\.(\d+))?$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CapabilityIO(_Strict):
    """What a capability takes or gives. ``text``: ``optional`` / ``required`` (input) or ``true``
    (output)."""

    files: list[str] = Field(default_factory=list, max_length=20)
    records: list[str] = Field(default_factory=list, max_length=20)
    text: Literal["optional", "required", True] | None = None

    @field_validator("files")
    @classmethod
    def _kinds(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - IO_FILE_KINDS)
        if unknown:
            raise ValueError(f"Unknown file kind(s): {', '.join(unknown)}")
        return value


class Capability(_Strict):
    """One thing a pack can do (spec §3.2, §10.1). Shaped like an A2A Agent Card skill (D12)."""

    key: str = Field(pattern=KEY_PATTERN)
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    input: CapabilityIO = Field(default_factory=CapabilityIO)
    output: CapabilityIO = Field(default_factory=CapabilityIO)
    examples: list[str] = Field(default_factory=list, max_length=10)
    typical_duration_s: int | None = Field(default=None, ge=1, le=86_400)
    manual_minutes_per_item: float | None = Field(default=None, ge=0, le=10_000)
    consultable: bool = False


class PackTrigger(_Strict):
    """A trigger as a pack declares it. Richer than a Phase 5 agent's (``plan_step``,
    project-setting filters, per-project schedules gated by a setting); the pack runtime reads
    these from code."""

    type: Literal["assigned", "mentioned", "manual", "plan_step", "event", "schedule"]
    event: str | None = Field(default=None, max_length=60)
    filter: dict[str, Any] | None = None
    cron: str | None = Field(default=None, max_length=100)
    timezone: str | None = Field(default=None, max_length=64)
    per: Literal["project"] | None = None
    setting: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def _shape(self) -> PackTrigger:
        if self.type == "event" and not self.event:
            raise ValueError("An event trigger needs `event`")
        if self.type == "schedule" and not self.cron:
            raise ValueError("A schedule trigger needs `cron`")
        if self.type not in ("event",) and (self.event or self.filter):
            raise ValueError("`event` / `filter` belong to event triggers")
        if self.type != "schedule" and (self.cron or self.timezone or self.per):
            raise ValueError("`cron` / `timezone` / `per` belong to schedule triggers")
        if self.setting and self.type not in ("event", "schedule"):
            raise ValueError(
                "`setting` (the consent switch) belongs to event and schedule triggers"
            )
        return self


class DataPolicy(_Strict):
    classification: Classification = "internal"
    personal_data: PersonalData = "none"
    reads_external_content: bool = False


class PackLimits(_Strict):
    """Per-job limits. Each is capped by a deployment ceiling (``MOMENTUM_AGENT_*``, spec §13.4);
    the loader refuses a manifest above a ceiling rather than quietly lowering it."""

    max_steps: int = Field(default=200, ge=1, le=10_000)
    step_timeout_s: int = Field(default=300, ge=10)
    max_active_s: int = Field(default=3600, ge=60)
    max_job_usd: float = Field(default=2.0, ge=0, le=1_000)
    max_job_tokens: int = Field(default=400_000, ge=0)
    concurrency: int = Field(default=4, ge=1)
    max_children: int = Field(default=500, ge=0)


Effect = Annotated[str | dict[str, list[str]], Field()]


class PackManifest(_Strict):
    key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=80)
    avatar: str = Field(default="teammate", pattern=AVATAR_PATTERN)
    version: str = Field(pattern=PACK_VERSION_PATTERN)
    sdk: str = Field(min_length=1, max_length=40)
    kind: PackKind
    description: str = Field(min_length=1, max_length=500)
    charter: str = Field(default="", max_length=20_000)
    capabilities: list[Capability] = Field(min_length=1, max_length=30)
    triggers: list[PackTrigger] = Field(default_factory=list, max_length=20)
    effects: list[Effect] = Field(default_factory=list, max_length=40)
    data: DataPolicy = Field(default_factory=DataPolicy)
    network: list[str] = Field(default_factory=list, max_length=0)  # the SDK gives no HTTP client
    secrets: list[str] = Field(default_factory=list, max_length=20)
    limits: PackLimits = Field(default_factory=PackLimits)
    model_alias: Literal["fast", "default", "smart"] = "default"
    budget_monthly_usd: float = Field(default=5.0, ge=0, le=10_000)
    budget_monthly_tokens: int = Field(default=2_000_000, ge=0, le=10_000_000_000)
    autonomy: Literal["suggest", "confirm"] = "confirm"  # "auto" is earned, never declared
    queue: Literal["ai", "heavy"] = "ai"
    commands: list[str] = Field(default_factory=list, max_length=20)
    resume_compatible_from: str | None = Field(default=None, pattern=PACK_VERSION_PATTERN)

    @field_validator("sdk")
    @classmethod
    def _sdk(cls, value: str) -> str:
        parse_range(value)  # raises ValueError with a readable message
        return value

    @field_validator("effects")
    @classmethod
    def _effects(cls, value: list[str | dict[str, list[str]]]) -> list[str | dict[str, list[str]]]:
        seen: set[str] = set()
        for item in value:
            if isinstance(item, str):
                name = item
                if name in EFFECTS_WITH_TYPES:
                    raise ValueError(f"Effect {name} needs its types, e.g. `- {name}: [invoice]`")
            else:
                if len(item) != 1:
                    raise ValueError("Each effect is one name, e.g. `- records.create: [invoice]`")
                ((name, types),) = item.items()
                if name not in EFFECTS_WITH_TYPES:
                    raise ValueError(f"Effect {name} takes no types")
                if not types or any(not re.match(KEY_PATTERN, t) for t in types):
                    raise ValueError(f"Effect {name}: give one or more type keys")
            if name not in EFFECT_NAMES:
                raise ValueError(
                    f"Unknown effect {name!r}; allowed: {', '.join(sorted(EFFECT_NAMES))}"
                )
            if name in seen:
                raise ValueError(f"Effect {name} is listed twice")
            seen.add(name)
        return value

    @model_validator(mode="after")
    def _unique(self) -> PackManifest:
        keys = [c.key for c in self.capabilities]
        if len(set(keys)) != len(keys):
            raise ValueError("Capability keys must be unique within a pack")
        if self.resume_compatible_from is not None and _semver(
            self.resume_compatible_from
        ) > _semver(self.version):
            raise ValueError("resume_compatible_from can't be newer than version")
        return self

    def declares(self, effect: str, type_key: str | None = None) -> bool:
        """Whether ``effect`` (for ``type_key``, when it takes types) is declared."""
        for item in self.effects:
            if isinstance(item, str) and item == effect:
                return True
            if isinstance(item, dict) and effect in item:
                return type_key is None or type_key in item[effect]
        return False


class ManifestError(ValueError):
    """A manifest that can't be used; the message names the file."""


def load_manifest(path: Path) -> PackManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return PackManifest.model_validate(raw)
    except FileNotFoundError as e:
        raise ManifestError(f"{path}: manifest not found") from e
    except (yaml.YAMLError, ValidationError) as e:
        raise ManifestError(f"{path}: {e}") from e


# ---------- SDK version ranges (">=1.0,<2"): no `packaging` dependency (D10) ----------


def _semver(value: str) -> tuple[int, int, int]:
    major, minor, patch = (int(x) for x in value.split("."))
    return major, minor, patch


def parse_range(spec: str) -> list[tuple[str, tuple[int, int]]]:
    """``">=1.0,<2"`` → ``[(">=", (1, 0)), ("<", (2, 0))]``. Versions are major[.minor]."""
    parts: list[tuple[str, tuple[int, int]]] = []
    for raw in spec.split(","):
        m = _RANGE_PART.match(raw.strip())
        if m is None:
            raise ValueError(
                f"sdk range {spec!r}: each part is an operator and a version, e.g. '>=1.0,<2'"
            )
        parts.append((m.group(1), (int(m.group(2)), int(m.group(3) or 0))))
    return parts


def in_range(version: str, spec: str) -> bool:
    """Whether SDK ``version`` (major.minor) satisfies the manifest's ``sdk`` range."""
    major, _, minor = version.partition(".")
    v = (int(major), int(minor or 0))
    ops = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a == b,
    }
    return all(ops[op](v, bound) for op, bound in parse_range(spec))
