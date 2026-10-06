# COAP invoice pipeline: reference source for Bernie (Phase 7.6)

The product owner's standalone invoice-extraction pipeline (from the COAP hackathon project, "COAP_Invoice_Notebook"), copied here **as reading material only** so the Phase 7.6 build session can port it into the Bernie pack (`packs/bernie/`). Files end in `.py.txt` so no tool lints, imports or runs them.

**Not copied** (and never to be added to this repo): the notebook's sample invoices, its `output/` results, `.env`, and its config/LLM client modules. Those hold or point at real vendor documents and gateway credentials. Bernie's tests use **synthetic invoices only** (spec §11).

## What each file teaches

| File | Port into Bernie as | Keep | Change |
|---|---|---|---|
| `invoice/extract.py.txt` | `bernie/extract.py` + prompts `bernie_extract/v1.md`, `bernie_extract_chunk/v1.md` | The "transcribe, do not compute" prompt rules (multi-page completeness, never infer, identifiers verbatim, DD/MM vs MM/DD by vendor country, US/EU numbers, negative credit notes, glyph self-check); page-range chunking above 8 pages (4 pages per chunk, header fields: last present wins) | Calls go through `job.llm` (aliases, budget, mock fixtures), JSON through the SDK's structured helper; images come from `momentum.files.render` |
| `invoice/classify.py.txt` | `bernie/vendors.py` | Match the **issuing entity** (letterhead, remit-to, tax id), never brand names in lines; closed vendor list, never invent a near match; a new vendor gets a slug id | The vendor list is the entity directory (`vendor` entities, pg_trgm alias match first, model only when that's ambiguous) |
| `invoice/reconcile.py.txt` | `bernie/checks/math.py` | **Zero model calls.** Total, date, currency, line numbering, and the "amount printed on its own row" provenance check; every check runs every time; `Decimal` money | Mismatches become record `checks` with severity; variance tolerances become pack settings |
| `invoice/self_check.py.txt` | `bernie/investigate.py` (first pass) | The critic gets the **exact** mismatch, a closed list of root causes, corrects extraction never arithmetic, re-validated by the reconciler; 3 attempts | Grows into the tool-using investigator (spec §9.5) |
| `invoice/pdf_utils.py.txt` | `bernie/ingest.py` | Boundary detection with the "different invoice number" rule and the PAGE N OF M guard; text-confidence heuristic; zip limits (500 entries, 25 MB each); sha256 dedupe; vendor hint from the folder name | **PyMuPDF (`fitz`) is AGPL: do not add it.** Split pages with `pypdf`; render with `momentum.files.render` (pypdfium2) |
| `invoice/ocr.py.txt` | (not ported) | | Tesseract is a system package. Scanned pages go to vision through the gateway (7.5 D4) |
| `invoice/skills.py.txt` | Bernie's `learn()` hook on the platform skills store | Hints describe **how to read** a field (position, label, quirk), never values or personal data; "generalizes: false" → no skill | Skills are database rows with propose → approve → active (spec §6), not auto-written YAML |
| `invoice/pipeline.py.txt` | `bernie/pipeline.py` (a durable job) | Stage order; one bad document never fails the batch; the composable correction primitives in `resolve_document` (field corrections, line patches, add lines, remove lines, distribute a bundled total evenly with the cent remainder on the last line) | Each stage is a job step; corrections come from the review screen |
| `invoice/catalogue.py.txt` | `bernie/catalogue.py` | Every column transcribed, never computed; excluded documents listed with a reason | Also an .xlsx through the 7.5 report writer |
| `invoice/llm_json.py.txt` | (platform SDK `job.llm.json()`) | Tolerate code fences and a prose preamble; retry empty content (≤ 4) | Lives in the SDK for every pack |
| `governance/policy.py.txt` | `bernie/policy.py` on the platform policy engine | Deny by default; ordered rules with ids and reasons; material amount and low confidence need a person | Thresholds are workspace pack settings, per currency; more rules (spec §9.8) |
| `redaction.py.txt` | (not ported) | Fail loud: a redaction failure must never look like success | Presidio + spaCy are too heavy; the SDK's regex scrubber covers skill hints and traces (spec §8.6) |
