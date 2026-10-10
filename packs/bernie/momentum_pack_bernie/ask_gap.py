"""`ask_gap` (spec §9.3.13): when the checks still fail after the critic and the investigator, one
form ask (to the requester, or the stewards when an agent asked) with what's printed vs the sum,
the gap and what Bernie tried, the totals area as evidence, and four answers. The answer becomes
correction operations or a re-split; Bernie never asks twice about the same invoice."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

REVIEW = "Send to review as extracted"
TOTAL = "The total is …"
SPLIT = "Pages … are a separate invoice"
LINE = "Line … should be …"
ACTIONS = [REVIEW, TOTAL, SPLIT, LINE]

FORM: list[dict[str, Any]] = [
    {
        "name": "action",
        "label": "What should Bernie do?",
        "type": "enum",
        "options": ACTIONS,
        "default": REVIEW,
    },
    {"name": "total", "label": "The total is", "type": "money", "required": False},
    {
        "name": "pages",
        "label": "Pages (e.g. 3-4) that are a separate invoice",
        "type": "text",
        "required": False,
    },
    {"name": "line", "label": "Line number", "type": "number", "required": False},
    {
        "name": "line_amount",
        "label": "That line's amount should be",
        "type": "money",
        "required": False,
    },
]
DEFAULT = {"value": {"action": REVIEW}}


def title(data: dict[str, Any]) -> str:
    who = data.get("vendor", {}).get("name") or "this invoice"
    number = data.get("invoice_number") or ""
    return f"Total doesn't add up on {who} {number}".strip()[:200]


def body(failing: list[dict[str, Any]], tried: list[str], currency: str | None) -> str:
    lines: list[str] = []
    for c in failing:
        if c.get("expected") is not None and c.get("observed") is not None:
            lines.append(
                f"- {c['title']}: printed {c['observed']} {currency or ''}, the lines add up to "
                f"{c['expected']} (a gap of {c.get('delta')})."
            )
        else:
            lines.append(f"- {c['title']}: {c.get('detail') or 'failed'}")
    out = "These checks still fail:\n" + "\n".join(lines)
    if tried:
        out += "\n\nWhat I tried:\n" + "\n".join(f"- {t}" for t in tried)
    out += (
        "\n\nTell me what's right, or send it to review as it is. If nobody answers, it goes to "
        "review as extracted."
    )
    return out[:5000]


def evidence(
    prov: dict[str, Any], failing: list[dict[str, Any]], file_id: str
) -> list[dict[str, Any]]:
    """The totals area and the rows the failing checks name, by page and box on the source."""
    fields = ["stated_total", "subtotal", "tax_amount"]
    for c in failing:
        fields += [f for f in c.get("fields") or [] if f not in fields]
    out: list[dict[str, Any]] = []
    for f in fields:
        p = prov.get(f) or {}
        if p.get("page"):
            item: dict[str, Any] = {
                "attachment_id": file_id,
                "page": p["page"],
                "excerpt": f.replace("_", " "),
            }
            if p.get("bbox"):
                item["bbox"] = p["bbox"]
            out.append(item)
    return out[:12]


def pages(text: str | None, page_count: int) -> tuple[int, int] | None:
    """``"3-4"`` / ``"3"`` / ``"pages 3 to 4"`` → (3, 4), within the document."""
    nums = [int(n) for n in re.findall(r"\d+", text or "")]
    if not nums:
        return None
    a, b = nums[0], nums[1] if len(nums) > 1 else nums[0]
    if a > b:
        a, b = b, a
    if a < 1 or b > page_count or (a == 1 and b == page_count):
        return None
    return a, b


def to_ops(value: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    """The answer's correction operations (empty: send to review as it is)."""
    action = value.get("action")
    if action == TOTAL and value.get("total") is not None:
        return [{"op": "set", "path": "stated_total", "value": _money(value["total"])}]
    if action == LINE and value.get("line") is not None and value.get("line_amount") is not None:
        n = int(Decimal(str(value["line"])))
        if 1 <= n <= len(data.get("lines") or []):
            return [
                {
                    "op": "set",
                    "path": f"lines[{n - 1}].amount",
                    "value": _money(value["line_amount"]),
                }
            ]
    return []


def apply_ops(data: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """The answer applied to a copy of the data (for the re-check before the record is made)."""
    out = {**data, "lines": [dict(li) for li in data.get("lines") or []]}
    for op in ops:
        m = re.fullmatch(r"lines\[(\d+)\]\.(\w+)", op["path"])
        if m:
            out["lines"][int(m.group(1))][m.group(2)] = op["value"]
        else:
            out[op["path"]] = op["value"]
    return out


def _money(v: Any) -> str:
    """A person's amount as the record keeps money: at least two decimals."""
    d = Decimal(str(v))
    exponent = d.as_tuple().exponent
    if isinstance(exponent, int) and exponent > -2:
        d = d.quantize(Decimal("0.01"))
    return format(d, "f")
