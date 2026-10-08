"""Phase 7.6: the loaded packs, by key, and their capabilities (built once per app or CLI run and
kept on the runtime, never as a module global)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from momentum.agents.packs.loader import Loaded, PackLoadError, load_packs
from momentum.agents.packs.manifest import Capability
from momentum.agents.packs.pack import Pack, PackError
from momentum.core.settings import Settings
from momentum.domain.agents.schemas import AgentDefinition


@dataclass
class PackRegistry:
    packs: dict[str, Pack] = field(default_factory=dict)
    errors: list[PackLoadError] = field(default_factory=list)

    @classmethod
    def load(cls, settings: Settings) -> PackRegistry:
        loaded: Loaded = load_packs(settings)
        return cls(dict(loaded.packs), list(loaded.errors))

    def get(self, key: str) -> Pack:
        pack = self.packs.get(key)
        if pack is None:
            raise PackError(f"No pack {key!r} is loaded")
        return pack

    def capability(self, pack_key: str, capability_key: str) -> Capability:
        return self.get(pack_key).capability(capability_key)

    def capabilities(self) -> list[tuple[str, Capability]]:
        """Every loaded capability as ``(pack key, capability)``, in pack order."""
        return [(k, c) for k, p in sorted(self.packs.items()) for c in p.manifest.capabilities]

    def definitions(self) -> list[tuple[AgentDefinition, str]]:
        """Each pack as the agent definition it installs (source ``pack``). Only the display and
        budget fields seed the row; capabilities, effects, data, limits and the pack's own
        triggers are read from the pack's code at run time."""
        out: list[tuple[AgentDefinition, str]] = []
        for key, pack in sorted(self.packs.items()):
            m = pack.manifest
            out.append(
                (
                    AgentDefinition(
                        key=key,
                        name=m.name,
                        avatar=m.avatar,
                        description=m.description,
                        instructions=m.charter,
                        kind="pack",
                        pack_key=key,
                        pack_version=m.version,
                        autonomy=m.autonomy,
                        model_alias=m.model_alias,
                        budget_monthly_usd=Decimal(f"{m.budget_monthly_usd:.2f}"),
                        budget_monthly_tokens=m.budget_monthly_tokens,
                    ),
                    "pack",
                )
            )
        return out


def packs_of(runtime: object) -> PackRegistry:
    """The runtime's registry, or an empty one outside a running app."""
    packs = getattr(runtime, "packs", None)
    return packs if isinstance(packs, PackRegistry) else PackRegistry()
