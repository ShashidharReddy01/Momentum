"""Versioned prompts (ai-architecture §7): ``prompts/<feature>/v<N>.md`` with YAML front matter
(``feature``, ``version``, ``alias``, ``max_tokens``, ``temperature``, ``output``) and a body that
may use ``{placeholders}``. ``load(feature)`` returns the latest version; the version is recorded
on ``llm_calls`` by passing ``prompt.version`` to the gateway. Prompts are package data, read
from disk once per process."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from momentum.ai.types import Alias

ROOT = Path(__file__).parent
_FRONT = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)


@dataclass(frozen=True)
class Prompt:
    feature: str
    version: str
    alias: Alias
    max_tokens: int
    temperature: float
    output: str
    body: str

    def render(self, **values: Any) -> str:
        return self.body.format(**values)


def _parse(path: Path) -> Prompt:
    m = _FRONT.match(path.read_text(encoding="utf-8"))
    if m is None:
        raise ValueError(f"{path}: missing front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    return Prompt(
        feature=str(meta["feature"]),
        version=f"{meta['feature']}/v{meta['version']}",
        alias=meta.get("alias", "default"),
        max_tokens=int(meta.get("max_tokens", 1500)),
        temperature=float(meta.get("temperature", 0.2)),
        output=str(meta.get("output", "text")),
        body=m.group(2).strip(),
    )


@functools.cache
def load(feature: str, version: int | None = None) -> Prompt:
    folder = ROOT / feature
    files = sorted(folder.glob("v*.md"), key=lambda p: int(p.stem[1:]))
    if not files:
        raise LookupError(f"no prompt for {feature}")
    chosen = files[-1] if version is None else folder / f"v{version}.md"
    return _parse(chosen)
