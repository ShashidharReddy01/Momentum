"""Where each value is printed (spec §6.3, §9.3.10), from the page words with positions.

**Provenance.** Each header value and line amount is searched for among the page's words in the
forms an invoice prints it (`1,250.00`, `1.250,00`, `1250.00`, `$1,250.00`, `(1,250.00)`…). A
unique match gets a box; for totals, among several matches the one beside its label ("Total",
"Amount due", "VAT"…) or else the last one on the page wins; vision-only pages get the page without
a box.

**Printed on its own row** (the notebook's `unsourced_value`, rebuilt on positions): a line's
amount must be printed on that line's row — the band of the line's description words — or the
next two rows below it (a wrapped description, the MSCI layout, puts the price under it). Two
fixes to the notebook's version, both seen on its real batch: a quantity-1 line whose unit price
equals its amount no longer "uses up" the only printed figure (every Haver line was flagged), and
the row is found by position rather than by one text line, so a table split across columns (D&B)
or a wrapped description still finds its amount. When the description's row can't be found at all
there's no evidence either way and nothing is flagged (as in the notebook).
"""

from __future__ import annotations

import itertools
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from momentum_pack_bernie.checks_math import check, dec
from momentum_pack_bernie.read import Page, Reading

_NUM = re.compile(r"[-(]?[\d][\d.,'\s]*\d|\d")
_LABELS = {
    "stated_total": (
        "total",
        "amount due",
        "balance due",
        "grand total",
        "invoice total",
        "total due",
    ),
    "subtotal": ("subtotal", "sub-total", "sub total", "net amount", "net total"),
    "tax_amount": ("tax", "vat", "gst", "mwst", "tva", "iva"),
    "amount_due": ("amount due", "balance due", "due"),
}


def parse_number(token: str) -> Decimal | None:
    """A printed number (US or EU format, symbols and brackets allowed) as a Decimal."""
    t = token.strip().replace("\u00a0", " ")
    neg = (t.startswith("(") and t.endswith(")")) or t.startswith("-") or t.endswith("-")
    t = re.sub(r"[^\d.,']", "", t)
    if not t:
        return None
    if "," in t and "." in t:
        t = (
            t.replace(",", "")
            if t.rfind(".") > t.rfind(",")
            else t.replace(".", "").replace(",", ".")
        )
    elif "," in t:
        head, _, tail = t.rpartition(",")
        t = (head.replace(",", "") + "." + tail) if len(tail) in (1, 2) else t.replace(",", "")
    t = t.replace("'", "")
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    return -d if neg else d


def _same(a: Decimal, b: Decimal) -> bool:
    return abs(abs(a) - abs(b)) < Decimal("0.005")


Box = tuple[float, float, float, float]


def _merge(words: list[Any]) -> list[tuple[str, Box]]:
    """Single words, and pairs of adjacent words on the same line ("1 250,00", "USD 1,250.00")."""
    out: list[tuple[str, Box]] = [(w[0], (w[1], w[2], w[3], w[4])) for w in words]
    for a, b in itertools.pairwise(words):
        if abs(a[2] - b[2]) < 3 and 0 <= b[1] - a[3] < 8:
            out.append((f"{a[0]} {b[0]}", (a[1], min(a[2], b[2]), b[3], max(a[4], b[4]))))
    return out


def find_amount(page: Page, value: Any) -> list[Box]:
    target = dec(value)
    if target is None:
        return []
    hits: list[Box] = []
    for text, box in _merge(page.words):
        if not any(ch.isdigit() for ch in text):
            continue
        n = parse_number(text)
        if (
            n is not None
            and _same(n, target)
            and not any(abs(box[1] - h[1]) < 2 and abs(box[0] - h[0]) < 2 for h in hits)
        ):
            hits.append(box)
    return hits


def find_text(page: Page, value: str) -> list[Box]:
    want = re.sub(r"\s+", "", str(value)).casefold()
    if len(want) < 2:
        return []
    hits: list[Box] = []
    for text, box in _merge(page.words):
        if re.sub(r"\s+", "", text).casefold().strip(":#.,") == want:
            hits.append(box)
    return hits


def _row_text(page: Page, top: float, tol: float = 3.0) -> str:
    return " ".join(w[0] for w in page.words if abs(w[2] - top) <= tol).casefold()


def _labelled(page: Page, field: str, boxes: list[Box]) -> Box | None:
    labels = _LABELS.get(field, ())
    labelled = [b for b in boxes if any(lbl in _row_text(page, b[1]) for lbl in labels)]
    if len(labelled) == 1:
        return labelled[0]
    if labelled:
        return max(labelled, key=lambda b: b[1])
    return max(boxes, key=lambda b: b[1]) if field in ("stated_total", "amount_due") else None


HEADER_TEXT = ("invoice_number", "po_number")
HEADER_MONEY = ("stated_total", "subtotal", "tax_amount", "amount_due", "discount", "shipping")


def _norm_words(text: str) -> list[str]:
    return [t for t in (re.sub(r"[^0-9a-z]", "", w.casefold()) for w in text.split()) if t]


def _desc_rows(page: Page, description: str) -> list[float]:
    """The `top` of rows where the line's description starts: its first words, whole and in
    order (so "seat 11" never matches the row of "seat 10 … 110.00")."""
    tokens = _norm_words(description)[:4]
    if not tokens:
        return []
    words = [(re.sub(r"[^0-9a-z]", "", w[0].casefold()), w[2]) for w in page.words]
    words = [w for w in words if w[0]]
    rows: list[float] = []
    for i, (text, top) in enumerate(words):
        if text != tokens[0]:
            continue
        if [w[0] for w in words[i : i + len(tokens)]] == tokens:
            rows.append(top)
    return rows


def _row_tops(page: Page) -> list[float]:
    tops: list[float] = []
    for w in sorted(page.words, key=lambda w: w[2]):
        if not tops or w[2] - tops[-1] > 3:
            tops.append(w[2])
    return tops


def line_amount_on_row(page: Page, line: dict[str, Any]) -> tuple[bool | None, Box | None]:
    """(printed on its row?, the amount's box). None when the description's row isn't found."""
    amount = dec(line.get("amount"))
    if amount is None:
        return None, None
    rows = _desc_rows(page, str(line.get("description") or ""))
    if len(rows) != 1:
        return None, None  # not found, or ambiguous: no evidence either way
    top = rows[0]
    tops = _row_tops(page)
    below = [t for t in tops if t > top + 3][:2]
    band = [top, *below]
    for box in find_amount(page, amount):
        if any(abs(box[1] - t) <= 3 for t in band):
            return True, box
    return False, None


def locate(data: dict[str, Any], reading: Reading) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Provenance per field, and the `unsourced_value` checks for line amounts."""
    prov: dict[str, Any] = {}
    readable = [p for p in reading.pages if p.source != "vision" and p.words]

    def place(field: str, boxes_by_page: list[tuple[Page, list[Box]]], money: bool) -> None:
        found = [(p, b) for p, bs in boxes_by_page for b in bs]
        if not found:
            return
        page, box = found[0]  # text printed more than once (header and footer): the first
        if money and len(found) > 1:
            chosen: tuple[Page, Box] | None = None
            for p, bs in reversed(boxes_by_page):
                pick = _labelled(p, field, bs) if bs else None
                if pick is not None:
                    chosen = (p, pick)
                    break
            if chosen is None:
                return  # several equal amounts and no label: no box rather than a wrong one
            page, box = chosen
        prov[field] = {
            "method": page.source,
            "page": page.n,
            "bbox": [round(v, 1) for v in box],
            "confidence": round(page.confidence, 3),
        }

    for field in HEADER_TEXT:
        if data.get(field):
            place(field, [(p, find_text(p, data[field])) for p in readable], False)
    for field in HEADER_MONEY:
        if data.get(field) is not None:
            place(field, [(p, find_amount(p, data[field])) for p in readable], True)

    checks: list[dict[str, Any]] = []
    for i, line in enumerate(data.get("lines") or []):
        if line.get("amount") is None:
            continue
        verdict: bool | None = None
        for p in readable:
            ok, box = line_amount_on_row(p, line)
            if ok:
                verdict = True
                prov[f"lines[{i}].amount"] = {
                    "method": p.source,
                    "page": p.n,
                    "bbox": [round(v, 1) for v in box],  # type: ignore[union-attr]
                    "confidence": round(p.confidence, 3),
                }
                break
            if ok is False:
                verdict = False
        if verdict is False:
            checks.append(
                check(
                    "unsourced_value",
                    False,
                    f"Line {i + 1}'s amount is printed on its row",
                    f"{line.get('amount')} isn't printed on the row of "
                    f"“{str(line.get('description'))[:60]}” or just below it: it may have been "
                    "computed (quantity x price) rather than read.",
                    fields=[f"lines[{i}].amount"],
                    failure_class="incomplete",
                )
            )
    if reading.vision_pages:
        for field in (*HEADER_TEXT, *HEADER_MONEY):
            if data.get(field) is not None and field not in prov and len(reading.vision_pages) == 1:
                prov[field] = {"method": "vision", "page": reading.vision_pages[0]}
    return prov, checks
