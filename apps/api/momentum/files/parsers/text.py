"""Text: .txt/.log as text; .md with headings as the outline; .json and .xml pretty-printed (XML
through defusedxml: no entities, no external references); .yaml as text; .html as text with
scripts and styles dropped."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser

from momentum.files.model import ParseResult
from momentum.files.parsers.base import Builder, section_locator
from momentum.files.parsers.sheets import decode_text
from momentum.files.safety import UnsafeFile

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
MAX_PRETTY = 200_000


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _HtmlText()
    p.feed(html)
    p.close()
    return re.sub(r"\n\s*\n+", "\n\n", "".join(p.parts)).strip()


def parse_text(data: bytes, filename: str, mime: str) -> ParseResult:
    b = Builder(data, filename, mime, "text")
    text = decode_text(data)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("md", "markdown") or mime == "text/markdown":
        path: list[str] = []
        buf: list[str] = []
        for line in text.splitlines():
            m = _MD_HEADING.match(line)
            if m:
                b.text("\n".join(buf), section_locator(path))
                buf = []
                level = len(m.group(1))
                path = [*path[: level - 1], m.group(2)]
                b.heading(m.group(2), level, section_locator(path))
            else:
                buf.append(line)
        b.text("\n".join(buf), section_locator(path))
        return b.done()
    if ext == "json" or mime == "application/json":
        try:
            pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except ValueError:
            b.warn("The JSON isn't valid: shown as plain text")
            pretty = text
        if len(pretty) > MAX_PRETTY:
            pretty = pretty[:MAX_PRETTY]
            b.header.truncated = True
            b.warn("The JSON is long: only the start is shown")
        b.text(pretty, "json")
        return b.done()
    if ext == "xml" or mime in ("application/xml", "text/xml"):
        from defusedxml import DefusedXmlException
        from defusedxml.minidom import parseString

        try:
            pretty = parseString(text).toprettyxml(indent="  ")
        except DefusedXmlException as e:
            raise UnsafeFile("The XML declares entities or external references") from e
        except Exception:
            b.warn("The XML isn't well-formed: shown as plain text")
            pretty = text
        if len(pretty) > MAX_PRETTY:
            pretty = pretty[:MAX_PRETTY]
            b.header.truncated = True
            b.warn("The XML is long: only the start is shown")
        b.text(pretty, "xml")
        return b.done()
    if ext in ("html", "htm") or mime == "text/html":
        b.text(html_to_text(text), "html")
        return b.done()
    # plain text: paragraphs as blocks, located by line
    at = 1
    for para in re.split(r"\n\s*\n", text):
        if para.strip():
            b.text(para, f"line {at}")
        at += para.count("\n") + 2
    return b.done()
