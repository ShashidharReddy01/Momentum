"""Phase 7.6 (spec §3.1, §11.2): the object a pack exports as ``pack`` (its ``momentum.packs`` entry
point). Re-exported by ``momentum.sdk``; packs build it, Momentum reads it.

S76-01 carries the manifest, the job function, capability handlers, the settings model and the
project setup. Later slices add record and entity types, policy, converse/answer/learn/profile/
recheck hooks and starter skills (spec §11.2); they arrive as more keyword arguments.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from momentum.agents.packs.entities import EntityType, load_starter_skills
from momentum.agents.packs.manifest import Capability, PackManifest, load_manifest
from momentum.agents.packs.records import RecordType
from momentum.agents.packs.setup import SetupItem

JobFn = Callable[..., Awaitable[Any]]


class PackSettings(BaseModel):
    """Base for a pack's settings model (spec §8.3). Every field needs a default, a title and help
    text; workspace values are overridden per project field by field (S76-05)."""

    model_config = ConfigDict(extra="forbid")


class PackError(Exception):
    """A pack that breaks the platform's rules (a developer error, caught in tests or at load)."""


@dataclass(eq=False)
class Pack:
    """A pack: ``Pack(manifest_path=Path(__file__).parent / "manifest.yaml", run=run, ...)``.

    ``run`` is the durable job function (S76-02). ``capabilities`` maps a capability key to its
    handler when it isn't the main ``run`` (e.g. a consultable ``explain_invoice``)."""

    manifest_path: Path
    run: JobFn | None = None
    capabilities: Mapping[str, JobFn] = field(default_factory=dict)
    settings: type[PackSettings] = PackSettings
    setup: tuple[SetupItem, ...] = ()
    # S76-03 (spec §5.6): the conversation handler, for "@Agent …" on a task with one of its jobs
    converse: JobFn | None = None
    # S76-04 (spec §6.1): the record types it produces
    record_types: tuple[RecordType, ...] = ()
    # S76-05 (spec §7.1, §8.3): the entity types it knows about
    entity_types: tuple[EntityType, ...] = ()

    @cached_property
    def starter_skills(self) -> list[dict[str, Any]]:
        """``skills/*.yaml`` next to the manifest (spec §7.2: generic rules only)."""
        return load_starter_skills(Path(self.manifest_path).parent)

    def entity_type(self, key: str) -> EntityType:
        for t in self.entity_types:
            if t.key == key:
                return t
        raise PackError(f"{self.key} has no entity type {key!r}")

    def record_type(self, key: str, version: int | None = None) -> RecordType:
        found = [t for t in self.record_types if t.key == key]
        if version is not None:
            found = [t for t in found if t.version == version]
        if not found:
            raise PackError(f"{self.key} has no record type {key!r}")
        return max(found, key=lambda t: t.version)

    @cached_property
    def manifest(self) -> PackManifest:
        return load_manifest(self.manifest_path)

    @property
    def key(self) -> str:
        return self.manifest.key

    def capability(self, key: str) -> Capability:
        for cap in self.manifest.capabilities:
            if cap.key == key:
                return cap
        raise PackError(f"{self.key} has no capability {key!r}")

    def validate(self) -> None:
        """Rules a loaded pack must meet beyond its manifest's own schema."""
        manifest = self.manifest
        declared = {c.key for c in manifest.capabilities}
        unknown = sorted(set(self.capabilities) - declared)
        if unknown:
            raise PackError(
                f"{manifest.key}: handlers for undeclared capabilities: {', '.join(unknown)}"
            )
        if not issubclass(self.settings, PackSettings):
            raise PackError(f"{manifest.key}: settings must subclass momentum.sdk.PackSettings")
        types = {t.key for t in self.record_types}
        if len({(t.key, t.version) for t in self.record_types}) != len(self.record_types):
            raise PackError(f"{manifest.key}: a record type version is listed twice")
        entities = {t.key for t in self.entity_types}
        for effect, known in (
            ("records.create", types),
            ("records.update", types),
            ("entities.create", entities),
            ("entities.update", entities),
        ):
            for item in manifest.effects:
                if isinstance(item, dict) and effect in item:
                    missing = sorted(set(item[effect]) - known)
                    if missing:
                        raise PackError(
                            f"{manifest.key}: {effect} names types it doesn't define:"
                            f" {', '.join(missing)}"
                        )
        if manifest.commands and self.converse is None:
            raise PackError(f"{manifest.key}: declares commands but has no converse handler")
        names = [(i.kind, i.name.casefold()) for i in self.setup]
        if len(set(names)) != len(names):
            raise PackError(f"{manifest.key}: setup lists the same item twice")
