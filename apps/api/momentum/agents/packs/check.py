"""Phase 7.6 (spec §11.1): ``momentum packs check``. Everything the loader enforces, reported as a
list instead of a log line, plus checks only a developer needs: an installed pack must have an
import-linter contract keeping it to ``momentum.sdk``. Later slices add asks-have-defaults,
effects-used ⊆ declared, the injection-eval rule, prompts and the determinism lint.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from momentum.agents.packs.loader import ENTRY_POINT_GROUP, load_packs
from momentum.core.settings import Settings

API_PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"
FACADE = "momentum.sdk"


def _contract_modules(pyproject: Path) -> set[str]:
    """Source modules that some import-linter contract forbids from importing Momentum's
    internals (anything under ``momentum.`` other than the SDK)."""
    if not pyproject.is_file():
        return set()
    data: dict[str, Any] = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    contracts = data.get("tool", {}).get("importlinter", {}).get("contracts", [])
    covered: set[str] = set()
    for c in contracts:
        forbidden = set(c.get("forbidden_modules", []))
        if c.get("type") == "forbidden" and {"momentum.domain", "momentum.core"} <= forbidden:
            covered.update(c.get("source_modules", []))
    return covered


def check_packs(
    settings: Settings, *, only: str | None = None, pyproject: Path = API_PYPROJECT
) -> list[str]:
    problems: list[str] = []
    loaded = load_packs(settings)
    for err in loaded.errors:
        if only is None or only in err.source:
            problems.append(f"{err.source}: {err.reason}")
    covered = _contract_modules(pyproject)
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if only is not None and ep.name != only:
            continue
        module = ep.value.split(":", 1)[0]
        if module not in covered:
            problems.append(
                f"entry point {ep.name}: no import-linter contract keeps {module} to {FACADE} "
                f"(add one to {pyproject.name}; `momentum packs new` does it for new packs)"
            )
    return problems
