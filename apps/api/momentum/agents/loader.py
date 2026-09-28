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

import yaml
from pydantic import ValidationError

from momentum.domain.agents.schemas import AgentDefinition

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
