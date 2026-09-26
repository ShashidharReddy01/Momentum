"""The tool catalog (ai-architecture §3): every tool Mo can call, assembled into a registry.

Built explicitly (no import-time registration), so an embedding host or a test can build a
registry with a subset or with its own tools added."""

from __future__ import annotations

from momentum.ai.tools import read_tools, write_tools
from momentum.ai.tools.base import Tool
from momentum.ai.tools.registry import ToolRegistry

CATALOG: tuple[Tool, ...] = (*read_tools.TOOLS, *write_tools.TOOLS)


def build_registry(*extra: Tool) -> ToolRegistry:
    return ToolRegistry((*CATALOG, *extra))
