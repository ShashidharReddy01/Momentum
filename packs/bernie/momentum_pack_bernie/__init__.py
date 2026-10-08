"""Bernie, the invoice agent (ADR-0013). Reads invoices (PDF, scans, e-invoices, zips), checks
every number, asks when unsure, and routes them for approval.

**Not built yet.** This is the S76-00 packaging skeleton only, so the pack installs and imports
cleanly; the real pack (manifest, pipeline, records, prompts) is built in S76-01 through S76-09+
(see docs/roadmap/phase-7.6.md). Importing this module must always succeed — the loader (S76-01)
is what will refuse to load an unbuilt pack — but using `pack` before then raises clearly.
"""

from __future__ import annotations

from typing import Any, NoReturn

NOT_BUILT_YET = (
    "Bernie is not built yet (Phase 7.6, S76-01 onward); see docs/roadmap/phase-7.6.md "
    "and docs/superpowers/specs/2026-10-06-phase-7-6-agent-platform-bernie-design.md"
)


class _NotBuiltYet:
    """Stands in for the real `momentum.sdk.Pack` object until S76-01+ builds it."""

    def __getattr__(self, name: str) -> NoReturn:
        raise NotImplementedError(NOT_BUILT_YET)

    def __repr__(self) -> str:
        return f"<momentum_pack_bernie.pack: {NOT_BUILT_YET}>"


pack: Any = _NotBuiltYet()
