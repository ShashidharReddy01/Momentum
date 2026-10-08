"""The public, versioned facade every pack imports (ADR-0012). A pack (`momentum_pack_*`) may
import only `momentum.sdk`, its own package and allowed third-party libraries — never
`momentum.domain`, `momentum.ai`, `momentum.agents`, `momentum.core` or `momentum.files` directly
(import-linter enforces this per pack). With 50-100+ packs, Momentum's internals must stay free
to change; only this module is a promise.

**Empty facade (S76-00).** `Pack`, `Job`, `step`, `ask`, records, entities, skills, settings,
policy, effects and the testing helpers are built incrementally from S76-01 onward (see
docs/roadmap/phase-7.6.md and the design spec's §11.2 SDK reference table). Each pack declares
`sdk: ">=1.0,<2"` in its manifest; the loader (S76-01) refuses a pack whose declared range this
version doesn't satisfy.
"""

from __future__ import annotations

SDK_VERSION = "1.0"

__all__ = ["SDK_VERSION"]
