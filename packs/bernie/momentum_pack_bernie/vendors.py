"""Who issued the invoice (spec §9.3.7), in the notebook's spirit of deterministic, free signals
first: the folder the file came in (the notebook trusted it over any model guess), a tax id on
page 1, a known vendor's name or alias in the letterhead; only then one cheap `fast` call that may
only pick from a closed list of known vendors or say "new" (an invented vendor is never trusted).
It's the issuing entity that counts (letterhead, remit-to, tax id), never a brand named in a line
("Bloomberg terminals" on a reseller's invoice is the reseller's invoice)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

LETTERHEAD_CHARS = 1500
MAX_CANDIDATES = 10

_TAX_ID = re.compile(
    r"\b(?:VAT\s*(?:Reg(?:istration)?|No|Number)?|USt-?IdNr|TVA|GST(?:\s*Reg)?|ABN|EIN|TIN|"
    r"Tax\s*ID)\.?\s*(?:No\.?|Number)?\s*[:#]?\s*"
    r"([A-Z]{0,2}[ -]?[0-9][0-9A-Z]*(?:[ -][0-9][0-9A-Z]*)*)",
    re.IGNORECASE,
)


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def tax_ids_in(text: str) -> list[str]:
    return [re.sub(r"[\s-]", "", m.group(1)).upper() for m in _TAX_ID.finditer(text)]


class Recognised(BaseModel):
    entity_id: str | None = None
    method: str | None = None  # folder | tax_id | letterhead | model
    candidates: list[str] = []  # entity ids, best first, when it's close


def recognise(page_one: str, hint: str | None, known: list[Any]) -> Recognised:
    """Deterministic recognition against the known vendors (`EntityView`s)."""
    if hint:
        for e in known:
            names = [e.name, *e.aliases, *((e.attributes or {}).get("folder_names") or [])]
            if any(slug(n) == hint for n in names):
                return Recognised(entity_id=str(e.id), method="folder")
    ids = set(tax_ids_in(page_one[: LETTERHEAD_CHARS * 2]))
    if ids:
        for e in known:
            mine = {
                re.sub(r"[\s-]", "", str(t)).upper()
                for t in (e.attributes or {}).get("tax_ids") or []
            }
            if mine & ids:
                return Recognised(entity_id=str(e.id), method="tax_id")
    head = squash(page_one[:LETTERHEAD_CHARS])
    hits: list[tuple[int, str]] = []
    for e in known:
        for n in [e.name, *e.aliases]:
            s = squash(n)
            if len(s) >= 4 and s in head:
                hits.append((head.index(s), str(e.id)))
                break
    if len(hits) == 1:
        return Recognised(entity_id=hits[0][1], method="letterhead")
    if hits:
        hits.sort()
        return Recognised(candidates=[h[1] for h in hits])
    return Recognised()


# Words that say nothing about who a company is ("Adatum Data Corp" isn't "Northwind Data Ltd")
GENERIC = frozenset(
    [
        "the",
        "and",
        "ltd",
        "limited",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "llc",
        "llp",
        "plc",
        "gmbh",
        "ag",
        "sa",
        "sas",
        "srl",
        "spa",
        "bv",
        "nv",
        "pte",
        "pty",
        "company",
        "group",
        "holdings",
        "holding",
        "international",
        "global",
        "worldwide",
        "data",
        "services",
        "service",
        "solutions",
        "systems",
        "technologies",
        "technology",
        "analytics",
        "research",
        "markets",
        "market",
        "financial",
        "finance",
        "information",
        "partners",
        "associates",
        "consulting",
        "media",
        "digital",
        "network",
        "networks",
        "software",
        "capital",
        "trading",
        "management",
        "invoice",
    ]
)


def _name_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.casefold()) if w not in GENERIC}


def candidates_for_model(page_one: str, known: list[Any]) -> list[Any]:
    """Up to 10 known vendors that share a distinctive word with the letterhead (generic company
    words don't count)."""
    words = _name_words(page_one[:LETTERHEAD_CHARS])

    def overlap(e: Any) -> int:
        return len(words & _name_words(" ".join([e.name, *e.aliases])))

    ranked = sorted(known, key=overlap, reverse=True)
    return [e for e in ranked if overlap(e) > 0][:MAX_CANDIDATES]


class VendorChoice(BaseModel):
    vendor_id: str  # one of the given ids, or "new"
    vendor_name_as_printed: str | None = None
    confidence: float = 0.0


def model_prompt(page_one: str, candidates: list[Any]) -> str:
    listing = "\n".join(
        f'- id "{e.id}": {e.name}' + (f" (also {', '.join(e.aliases)})" if e.aliases else "")
        for e in candidates
    )
    return (
        'known vendors (the only ids you may answer with, besides "new"):\n'
        f"{listing}\n\n<untrusted_document>\n{page_one[:LETTERHEAD_CHARS]}\n</untrusted_document>"
    )
