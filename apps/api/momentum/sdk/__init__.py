"""The public, versioned facade every pack imports (ADR-0012). A pack (`momentum_pack_*`) may
import only `momentum.sdk`, its own package and allowed third-party libraries — never
`momentum.domain`, `momentum.ai`, `momentum.agents`, `momentum.core` or `momentum.files` directly
(import-linter enforces this per pack). With 50-100+ packs, Momentum's internals must stay free
to change; only this module is a promise.

Each pack declares `sdk: ">=1.0,<2"` in its manifest; the loader refuses a pack whose declared
range this version doesn't satisfy. The surface grows slice by slice (design spec §11.2):
S76-01 adds `Pack`, `Capability`, `PackSettings` and the setup items (`TaskField`, `Section`).
"""

from __future__ import annotations

from momentum.agents.packs.loader import SDK_VERSION
from momentum.agents.packs.manifest import Capability, PackManifest
from momentum.agents.packs.pack import Pack, PackError, PackSettings
from momentum.agents.packs.setup import Section, TaskField

__all__ = [
    "SDK_VERSION",
    "Capability",
    "Pack",
    "PackError",
    "PackManifest",
    "PackSettings",
    "Section",
    "TaskField",
]
