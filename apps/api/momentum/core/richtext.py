"""Rich text (Tiptap/ProseMirror JSON): validation, sanitizing, plain-text extraction, hashing.

Rich text is stored as the editor's JSON document. The server never trusts it: only known node and
mark types are accepted, links keep only safe protocols, and size and depth are capped. Rendering
happens in the editor (no HTML is stored), so this is the whole XSS surface for rich text.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlparse

from momentum.core.errors import ValidationFailed

MAX_BYTES = 256_000
MAX_DEPTH = 24
MAX_TEXT = 100_000

NODES: dict[str, set[str]] = {
    # node type -> allowed attrs
    "doc": set(),
    "paragraph": set(),
    "text": set(),
    "heading": {"level"},
    "bulletList": set(),
    "orderedList": {"start", "type"},
    "listItem": set(),
    "taskList": set(),
    "taskItem": {"checked"},
    "codeBlock": {"language"},
    "blockquote": set(),
    "hardBreak": set(),
    "horizontalRule": set(),
    "mention": {"id", "label", "kind"},
}
MARKS: dict[str, set[str]] = {
    "bold": set(),
    "italic": set(),
    "strike": set(),
    "underline": set(),
    "code": set(),
    "link": {"href"},
}
SAFE_SCHEMES = {"http", "https", "mailto"}
BLOCKS_WITH_BREAK = {"paragraph", "heading", "codeBlock", "listItem", "taskItem", "blockquote"}


def _safe_href(href: object) -> str | None:
    if not isinstance(href, str) or len(href) > 2048:
        return None
    href = href.strip()
    scheme = urlparse(href).scheme.lower()
    return href if scheme in SAFE_SCHEMES else None


def _clean_attrs(node_type: str, attrs: object) -> dict[str, Any] | None:
    if not isinstance(attrs, dict):
        return None
    allowed = NODES[node_type]
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if key not in allowed or value is None:
            continue
        if key == "level":
            if not isinstance(value, int) or not 1 <= value <= 3:
                raise ValidationFailed("Headings go from level 1 to 3", code="invalid_rich_text")
        elif key == "checked":
            value = bool(value)
        elif key in ("start",):
            if not isinstance(value, int) or not 0 <= value <= 100_000:
                continue
        elif isinstance(value, str):
            value = value[:200]
        else:
            continue
        out[key] = value
    return out or None


def _clean_node(node: object, depth: int) -> dict[str, Any] | None:
    if depth > MAX_DEPTH:
        raise ValidationFailed("The text is nested too deeply", code="invalid_rich_text")
    if not isinstance(node, dict):
        raise ValidationFailed("Invalid rich text", code="invalid_rich_text")
    node_type = node.get("type")
    if node_type not in NODES:
        raise ValidationFailed(
            f"Unsupported content: {str(node_type)[:40]}", code="invalid_rich_text"
        )
    out: dict[str, Any] = {"type": node_type}
    attrs = _clean_attrs(node_type, node.get("attrs"))
    if attrs:
        out["attrs"] = attrs
    if node_type == "text":
        text = node.get("text")
        if not isinstance(text, str) or text == "":
            return None  # ProseMirror forbids empty text nodes
        out["text"] = text
        marks = []
        for mark in node.get("marks") or []:
            if not isinstance(mark, dict) or mark.get("type") not in MARKS:
                continue
            clean: dict[str, Any] = {"type": mark["type"]}
            if mark["type"] == "link":
                href = _safe_href((mark.get("attrs") or {}).get("href"))
                if href is None:
                    continue  # drop unsafe links, keep the text
                clean["attrs"] = {"href": href}
            marks.append(clean)
        if marks:
            out["marks"] = marks
        return out
    children = node.get("content")
    if children is not None:
        if not isinstance(children, list):
            raise ValidationFailed("Invalid rich text", code="invalid_rich_text")
        content = [c for c in (_clean_node(child, depth + 1) for child in children) if c]
        if content:
            out["content"] = content
    return out


def plain_text(doc: dict[str, Any] | None) -> str:
    """Readable text of a document (for search, previews, and AI context)."""
    if not doc:
        return ""
    parts: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "text":
            parts.append(str(node.get("text", "")))
        elif node.get("type") == "hardBreak":
            parts.append("\n")
        elif node.get("type") == "mention":
            parts.append("@" + str((node.get("attrs") or {}).get("label", "")))
        for child in node.get("content") or []:
            walk(child)
        if node.get("type") in BLOCKS_WITH_BREAK:
            parts.append("\n")

    walk(doc)
    lines = [line.rstrip() for line in "".join(parts).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def sanitize_doc(doc: object) -> dict[str, Any] | None:
    """Validate and clean a document. Empty documents become None."""
    if doc is None:
        return None
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise ValidationFailed("Invalid rich text", code="invalid_rich_text")
    if len(json.dumps(doc, separators=(",", ":"))) > MAX_BYTES:
        raise ValidationFailed("The text is too long", code="rich_text_too_large")
    clean = _clean_node(doc, 0)
    assert clean is not None
    text = plain_text(clean)
    if len(text) > MAX_TEXT:
        raise ValidationFailed("The text is too long", code="rich_text_too_large")
    has_structure = any(
        n.get("type") in ("horizontalRule", "taskList") for n in clean.get("content") or []
    )
    if not text and not has_structure:
        return None
    return clean


def doc_hash(doc: dict[str, Any] | None) -> str:
    """Short, stable fingerprint of a document ("" for none): clients send back the hash of the
    description they started editing, so concurrent edits are detected precisely."""
    if doc is None:
        return ""
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def preview(doc: dict[str, Any] | None, limit: int = 140) -> str | None:
    text = plain_text(doc).replace("\n", " ")
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"
