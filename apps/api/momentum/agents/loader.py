"""S5.1.1: agent definition files → validated ``AgentDefinition``s.

Momentum's starter agents live in ``momentum/agents/definitions/*.yaml`` (source ``starter``).
A host application adds its own by passing directories to ``create_app(agent_definition_dirs=…)``
or ``momentum agents install --definitions-dir`` (source ``host``; ADR-0009). One file per agent,
named after its ``key``. Keys are unique across all directories: a host can't silently replace a
starter agent, it defines its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from momentum.domain.agents.schemas import AgentDefinition

if TYPE_CHECKING:
    from momentum.agents.packs.registry import PackRegistry

PACKAGED_DIR = Path(__file__).parent / "definitions"


class DefinitionError(ValueError):
    """A definition file that can't be used; the message names the file."""


def load_definitions(extra_dirs: Sequence[Path | str] = ()) -> list[tuple[AgentDefinition, str]]:
    """All definitions as ``(definition, source)`` pairs, starters first, each directory in
    file-name order."""
    found: list[tuple[AgentDefinition, str]] = []
    seen: dict[str, Path] = {}
    for directory, source in [(PACKAGED_DIR, "starter"), *((Path(d), "host") for d in extra_dirs)]:
        if not directory.is_dir():
            raise DefinitionError(f"Agent definitions directory not found: {directory}")
        for path in sorted(directory.glob("*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                definition = AgentDefinition.model_validate(raw)
            except (yaml.YAMLError, ValidationError) as e:
                raise DefinitionError(f"{path.name}: {e}") from e
            if definition.key != path.stem:
                raise DefinitionError(
                    f"{path.name}: key {definition.key!r} must match the file name"
                )
            if definition.key in seen:
                where = seen[definition.key]
                raise DefinitionError(
                    f"{path.name}: key {definition.key!r} is already defined in {where}"
                )
            seen[definition.key] = path
            found.append((definition, source))
    return found


def all_definitions(
    extra_dirs: Sequence[Path | str], packs: PackRegistry
) -> list[tuple[AgentDefinition, str]]:
    """YAML definitions plus one per loaded pack (Phase 7.6; source ``pack``). A pack can't take a
    key a definition file already uses."""
    found = load_definitions(extra_dirs)
    taken = {d.key for d, _ in found}
    for definition, source in packs.definitions():
        if definition.key in taken:
            raise DefinitionError(
                f"pack {definition.key!r}: an agent definition file already uses that key"
            )
        found.append((definition, source))
    return found
