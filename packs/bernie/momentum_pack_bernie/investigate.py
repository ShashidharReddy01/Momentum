"""The investigator (spec §9.3.12, second half; ADR-0013 decision 7): when the critic couldn't make
the checks pass, a bounded tool loop (`smart`, at most 8 turns) with read tools over **this
document only** — page text, rows with positions, find, exact sums — and `propose_fix`, which
applies changes to a scratch copy and returns the re-run checks. The loop ends when the checks
pass, the model stops, or the turns run out.

Grounding is enforced in code, never trusted to the model: a value in a proposed fix must have
appeared in a tool result during this investigation (a figure the tools never showed is rejected
with a reason the model sees)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from momentum_pack_bernie.extract import Extracted, _money
from momentum_pack_bernie.locate import find_amount, find_text, parse_number
from momentum_pack_bernie.read import Reading

MAX_TURNS = 8
_NUM = re.compile(r"[-(]?\d[\d.,']*\d|\d")

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "page_text",
            "description": "The text of one page of this invoice.",
            "parameters": {
                "type": "object",
                "properties": {"page": {"type": "integer"}},
                "required": ["page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rows",
            "description": (
                "The rows of one page as printed (words joined left to right), with their "
                "vertical position, for reading tables."
            ),
            "parameters": {
                "type": "object",
                "properties": {"page": {"type": "integer"}},
                "required": ["page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find",
            "description": (
                "Where a number or a word is printed in this invoice (page and position)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sum",
            "description": (
                "The exact sum of some amounts (server arithmetic; never add up yourself)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"values": {"type": "array", "items": {"type": "string"}}},
                "required": ["values"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_fix",
            "description": (
                "Apply changes to a scratch copy of the extraction and get the checks back. "
                'Each change is {"field": "stated_total|subtotal|tax_amount|currency|'
                'invoice_date|invoice_number", "value": "..."}, '
                '{"line": N, "field": "amount|description|quantity|unit_price", "value": "..."}, '
                '{"remove_line": N} or {"add_line": {"description": "...", "amount": "..."}}. '
                "Every value must be one the other tools showed you."
            ),
            "parameters": {
                "type": "object",
                "properties": {"changes": {"type": "array", "items": {"type": "object"}}},
                "required": ["changes"],
            },
        },
    },
]


def _rows(reading: Reading, page: int) -> list[str]:
    p = next((x for x in reading.pages if x.n == page), None)
    if p is None:
        return []
    out: list[tuple[float, list[Any]]] = []
    for w in sorted(p.words, key=lambda w: (w[2], w[1])):
        if out and abs(out[-1][0] - w[2]) <= 3:
            out[-1][1].append(w)
        else:
            out.append((w[2], [w]))
    return [
        f"y={round(top)}: " + " ".join(x[0] for x in sorted(ws, key=lambda x: x[1]))
        for top, ws in out
    ]


class Investigation:
    """One investigation: the tools over a reading, the scratch extraction, the values seen."""

    def __init__(
        self,
        reading: Reading,
        extracted: Extracted,
        recheck: Callable[[Extracted], list[dict[str, Any]]],
    ) -> None:
        self.reading = reading
        self.current = extracted
        self.recheck = recheck
        self.seen: set[Decimal] = set()
        self.seen_text: list[str] = []
        self.clean = False

    def _remember(self, text: str) -> None:
        self.seen_text.append(text.casefold())
        for m in _NUM.finditer(text):
            n = parse_number(m.group(0))
            if n is not None:
                self.seen.add(abs(n))

    def run(self, name: str, args: dict[str, Any]) -> str:
        try:
            out = self._run(name, args)
        except (ValueError, KeyError, TypeError, InvalidOperation) as e:
            out = {"error": str(e)[:300]}
        text = json.dumps(out, default=str)
        if name != "propose_fix":
            self._remember(text)
        return text

    def _run(self, name: str, args: dict[str, Any]) -> Any:
        if name == "page_text":
            p = next((x for x in self.reading.pages if x.n == int(args["page"])), None)
            if p is None:
                return {"error": f"No page {args['page']}"}
            if p.source == "vision":
                return {"error": "This page is an image without readable text"}
            return {"page": p.n, "text": p.text[:8000]}
        if name == "rows":
            return {"page": int(args["page"]), "rows": _rows(self.reading, int(args["page"]))[:200]}
        if name == "find":
            text = str(args["text"])
            hits: list[dict[str, Any]] = []
            for p in self.reading.pages:
                boxes = (
                    find_amount(p, text)
                    if parse_number(text) is not None and any(c.isdigit() for c in text)
                    else []
                )
                boxes = boxes or find_text(p, text)
                hits += [{"page": p.n, "bbox": [round(v) for v in b], "text": text} for b in boxes]
            return {"matches": hits[:20]}
        if name == "sum":
            values = [parse_number(str(v)) for v in args["values"]]
            if any(v is None for v in values):
                return {"error": "Every value must be a number"}
            return {"sum": format(sum((v for v in values if v is not None), Decimal(0)), "f")}
        if name == "propose_fix":
            return self.propose(list(args.get("changes") or []))
        return {"error": f"Unknown tool {name}"}

    def _ok_value(self, field: str, value: Any) -> str | None:
        """Why a value can't be used, or None when it can (it was shown by a tool)."""
        if field in ("amount", "quantity", "unit_price", "stated_total", "subtotal", "tax_amount"):
            n = parse_number(str(value))
            if n is None:
                return f"{value!r} isn't a number"
            if abs(n) not in self.seen:
                return f"{value} wasn't shown by any tool on this document; find it first"
            return None
        if field in ("currency", "invoice_number", "description", "invoice_date"):
            text = str(value).casefold()
            if field == "invoice_date":
                return None  # a date is normalised; the page shows it in another form
            if not any(text in t for t in self.seen_text):
                return f"{value!r} wasn't shown by any tool on this document"
            return None
        return f"{field} can't be changed here"

    def propose(self, changes: list[dict[str, Any]]) -> dict[str, Any]:
        data = self.current.model_dump()
        lines = data["line_items"]
        for ch in changes:
            if "remove_line" in ch:
                n = int(ch["remove_line"])
                if not 1 <= n <= len(lines):
                    return {"rejected": f"There's no line {n}"}
                lines.pop(n - 1)
            elif "add_line" in ch:
                li = dict(ch["add_line"])
                for f in ("amount", "description"):
                    why = self._ok_value(f, li.get(f))
                    if why:
                        return {"rejected": why}
                lines.append({"line_number": 0, **li})
            elif "line" in ch:
                n, field = int(ch["line"]), str(ch["field"])
                why = self._ok_value(field, ch.get("value"))
                if why:
                    return {"rejected": why}
                if not 1 <= n <= len(lines):
                    return {"rejected": f"There's no line {n}"}
                lines[n - 1][field] = ch.get("value")
            elif "field" in ch:
                field = str(ch["field"])
                why = self._ok_value(field, ch.get("value"))
                if why:
                    return {"rejected": why}
                data[field] = ch.get("value")
        for i, li in enumerate(lines, start=1):
            li["line_number"] = i
        candidate = Extracted.model_validate(data)
        failing = [
            c for c in self.recheck(candidate) if not c["passed"] and c["severity"] == "block"
        ]
        self.current = candidate
        self.clean = not failing
        return {
            "applied": len(changes),
            "checks_failing": [{"id": c["id"], "detail": c.get("detail")} for c in failing],
            "clean": self.clean,
        }


def opening(extracted: Extracted, failing: list[dict[str, Any]], pages: int) -> str:
    return (
        f"The invoice has {pages} page(s). Its extraction fails these checks:\n"
        + json.dumps([{"id": c["id"], "detail": c.get("detail")} for c in failing], indent=2)
        + "\n\nThe extraction:\n"
        + json.dumps(extracted.model_dump(), indent=2, default=str)[:12000]
        + "\n\nInvestigate with the tools and propose a fix that makes the checks pass. Stop when"
        " they pass, or say plainly that the document doesn't let you fix it."
    )


def money_text(v: Any) -> str | None:
    return _money(v)
