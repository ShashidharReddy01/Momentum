"""Phase 7.6 S76-05 (spec §7.1): entity types, as packs declare them (``momentum.sdk.EntityType``).

An entity type is a key (``vendor``), a label and a pydantic model for its ``attributes``. A pack
may add a ``profile`` hook: pure code that turns an entity's approved records into statistics
(median totals, cadence, usual tax rates…), run nightly by ``compute_entity_profiles``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict


class EntityModel(BaseModel):
    """Base for a pack's entity attributes model (e.g. ``VendorAttributes``)."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class EntityType:
    key: str
    model: type[EntityModel]
    label: str
    profile_fn: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if not re.match(r"^[a-z][a-z0-9_]{0,39}$", self.key):
            raise ValueError(f"Entity type key {self.key!r} isn't a lower-case key")

    def validate(self, attributes: dict[str, Any]) -> dict[str, Any]:
        return self.model.model_validate(attributes).model_dump(mode="json", exclude_none=True)


def load_starter_skills(pack_dir: Path) -> list[dict[str, Any]]:
    """A pack's starter skills: ``skills/*.yaml``, each a list of ``{key, kind, content, field?}``
    (generic only: never anything about a real vendor or customer)."""
    folder = pack_dir / "skills"
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        items = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(items, list):
            raise ValueError(f"{path}: a list of skills")
        for item in items:
            if not isinstance(item, dict) or not {"key", "kind", "content"} <= set(item):
                raise ValueError(f"{path}: each skill has a key, a kind and content")
            out.append(item)
    keys = [i["key"] for i in out]
    if len(keys) != len(set(keys)):
        raise ValueError(f"{folder}: starter skill keys must be unique")
    return out
