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

from momentum.agents.packs.manifest import Capability, PackManifest, load_manifest
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
        names = [(i.kind, i.name.casefold()) for i in self.setup]
        if len(set(names)) != len(names):
            raise PackError(f"{manifest.key}: setup lists the same item twice")
