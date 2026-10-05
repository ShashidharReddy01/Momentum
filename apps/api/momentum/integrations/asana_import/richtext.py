"""Asana rich text (``html_notes``, a story's ``html_text``) → Momentum's Tiptap documents
(`docs/integrations/asana-import.md §3`).

Asana's HTML is a small, well-formed subset wrapped in ``<body>``: ``<strong> <em> <u> <s>
<code> <a href> <ul> <ol> <li> <h1> <h2> <hr> <blockquote> <pre>`` and newlines as line breaks.
Anything else keeps its text and drops its tag. ``<a data-asana-gid>`` (an @mention of a person
or task) becomes a plain link to it, or its text when it has no usable link. The result always
goes through ``core.richtext.sanitize_doc``, so nothing unsafe survives whatever Asana sends.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from momentum.core.errors import ValidationFailed
from momentum.core.richtext import sanitize_doc

INLINE_MARKS = {
    "strong": "bold",
    "b": "bold",
    "em": "italic",
    "i": "italic",
    "u": "underline",
    "s": "strike",
    "strike": "strike",
    "del": "strike",
    "code": "code",
}
BLOCKS = {"p", "h1", "h2", "h3", "li", "blockquote", "pre", "ul", "ol", "body"}


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doc: dict[str, Any] = {"type": "doc", "content": []}
        self.stack: list[dict[str, Any]] = [self.doc]  # open block nodes
        self.marks: list[dict[str, Any]] = []
        self.para: dict[str, Any] | None = None  # the inline container being filled

    # ---- helpers ----

    def _container(self) -> dict[str, Any]:
        return self.stack[-1]

    def _inline_target(self) -> dict[str, Any]:
        """Where text goes: the open paragraph/heading/code block, or a new paragraph."""
        top = self._container()
        if top["type"] in ("paragraph", "heading", "codeBlock"):
            return top
        if self.para is None or self.para not in top.get("content", []):
            self.para = {"type": "paragraph", "content": []}
            top.setdefault("content", []).append(self.para)
        return self.para

    def _open(self, node: dict[str, Any]) -> None:
        self._container().setdefault("content", []).append(node)
        self.stack.append(node)
        self.para = None

    def _close(self, *types: str) -> None:
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["type"] in types:
                del self.stack[i:]
                break
        self.para = None

    def _text(self, text: str) -> None:
        if not text:
            return
        target = self._inline_target()
        in_code = target["type"] == "codeBlock"
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if i:
                if in_code:
                    line = "\n" + line
                else:
                    target.setdefault("content", []).append({"type": "hardBreak"})
            if line:
                node: dict[str, Any] = {"type": "text", "text": line}
                if self.marks and not in_code:
                    node["marks"] = [dict(m) for m in self.marks]
                target.setdefault("content", []).append(node)

    # ---- parser callbacks ----

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in INLINE_MARKS:
            self.marks.append({"type": INLINE_MARKS[tag]})
        elif tag == "a":
            href = a.get("href") or ""
            self.marks.append({"type": "link", "attrs": {"href": href}} if href else {"type": "_"})
        elif tag == "br":
            self._text("\n")
        elif tag == "p":
            self._open({"type": "paragraph", "content": []})
        elif tag in ("h1", "h2", "h3"):
            self._open(
                {"type": "heading", "attrs": {"level": 2 if tag == "h1" else 3}, "content": []}
            )
        elif tag == "ul":
            self._open({"type": "bulletList", "content": []})
        elif tag == "ol":
            self._open({"type": "orderedList", "content": []})
        elif tag == "li":
            if self._container()["type"] not in ("bulletList", "orderedList"):
                self._open({"type": "bulletList", "content": []})
            self._open({"type": "listItem", "content": []})
        elif tag == "blockquote":
            self._open({"type": "blockquote", "content": []})
        elif tag == "pre":
            self._open({"type": "codeBlock", "content": []})
        elif tag == "hr":
            self._container().setdefault("content", []).append({"type": "horizontalRule"})
            self.para = None

    def handle_endtag(self, tag: str) -> None:
        if tag in INLINE_MARKS or tag == "a":
            if self.marks:
                self.marks.pop()
        elif tag == "p":
            self._close("paragraph")
        elif tag in ("h1", "h2", "h3"):
            self._close("heading")
        elif tag in ("ul", "ol"):
            self._close("bulletList", "orderedList")
        elif tag == "li":
            self._close("listItem")
        elif tag == "blockquote":
            self._close("blockquote")
        elif tag == "pre":
            self._close("codeBlock")

    def handle_data(self, data: str) -> None:
        if self._container()["type"] in ("doc", "bulletList", "orderedList") and not data.strip():
            return  # whitespace between blocks
        self._text(data)


def _strip_placeholders(node: dict[str, Any]) -> None:
    for child in node.get("content") or []:
        if child.get("marks"):
            child["marks"] = [m for m in child["marks"] if m["type"] != "_"] or None
            if child["marks"] is None:
                del child["marks"]
        _strip_placeholders(child)
    # lists and quotes need block children; empty containers are dropped
    if node.get("content") is not None:
        node["content"] = [
            c
            for c in node["content"]
            if c.get("type") in ("text", "hardBreak", "horizontalRule") or c.get("content")
        ]


def html_to_doc(html: str | None, plain: str | None = None) -> dict[str, Any] | None:
    """Asana HTML (or, failing that, its plain ``notes``) → a sanitized Tiptap document, or
    None when there's nothing to keep."""
    source = html if html and html.strip() else None
    if source is None:
        if not plain or not plain.strip():
            return None
        source = "<body>" + plain.replace("&", "&amp;").replace("<", "&lt;") + "</body>"
    b = _Builder()
    b.feed(source)
    b.close()
    _strip_placeholders(b.doc)
    try:
        return sanitize_doc(b.doc)
    except ValidationFailed:
        # too large or malformed after all: keep the words, lose the formatting
        text = plain or ""
        return (
            sanitize_doc(
                {
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": text[:90_000]}]}
                    ],
                }
            )
            if text.strip()
            else None
        )
