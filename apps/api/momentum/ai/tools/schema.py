"""Tool argument models → JSON Schema in the OpenAI ``tools`` format (and, in Phase 7, MCP).

Pydantic's schema is post-processed so every gateway and model family accepts it: ``$ref``s are
inlined (some providers reject ``$defs``), and the auto-generated ``title`` keys are dropped
(they cost tokens and carry no meaning). Field descriptions are kept: they are the model's
documentation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from momentum.ai.tools.base import ToolSpec
from momentum.ai.types import ToolSchema


def args_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs: dict[str, Any] = raw.pop("$defs", {})
    out = _inline(raw, defs, depth=0)
    assert isinstance(out, dict)
    out.setdefault("properties", {})
    return out


def _inline(node: Any, defs: dict[str, Any], *, depth: int) -> Any:
    if depth > 20:  # argument models are shallow; a deeper walk means a recursive model
        raise ValueError("tool argument schemas must not be recursive")
    if isinstance(node, list):
        return [_inline(x, defs, depth=depth) for x in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target = defs[node["$ref"].rsplit("/", 1)[-1]]
        merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        return _inline(merged, defs, depth=depth + 1)
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title" and isinstance(value, str):
            continue
        if key == "properties" and isinstance(value, dict):
            # property names are data here, not schema keywords (a field may be called "title")
            out[key] = {k: _inline(v, defs, depth=depth) for k, v in value.items()}
        else:
            out[key] = _inline(value, defs, depth=depth)
    return out


def tool_schema(spec: ToolSpec) -> ToolSchema:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": args_schema(spec.args_model),
        },
    }
