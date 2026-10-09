# ADR-0014: OCR scanned invoices with Tesseract before vision

- **Status:** Accepted (amends ADR-0013 decision 3, for OCR only)
- **Date:** 2026-10-09
- **Deciders:** product owner, AI (drafted)

## Context
ADR-0013 (decision 3, "D10") ruled out Tesseract because it's a system package, sending scanned pages to the gateway model as images instead. Before Bernie's extraction was built (S76-09), the product owner set the bar for Bernie explicitly: extraction quality is the whole point ("all i need is extraction quality to be topnotch", 99.99% field accuracy), the COAP notebook's pipeline is "well thought through" and should be ported faithfully, and whatever achieves the accuracy is acceptable. The notebook's order for a scanned document is text layer → **OCR (Tesseract)** → vision only if the text is still poor, and its provenance check ("is this amount printed on its own row") needs words, which only a text layer or OCR provides.

## Decision
1. **OCR comes before vision for scanned or low-quality pages**, as in the notebook: a page whose text layer is empty or below the 0.75 text-confidence floor is rendered and OCR'd; only if the OCR text is still below the floor does it go to vision. OCR words keep their positions, so scanned pages get the same provenance boxes and row checks as digital ones.
2. **Tesseract is a system dependency of the server image** (`infra/docker/Dockerfile`: `tesseract-ocr` plus English, German, French, Spanish, Italian and Dutch language packs), called through `pytesseract` (a small pure-Python wrapper, the one new runtime dependency). OCR runs locally in the process: no document content leaves the server for OCR.
3. **OCR lives in Momentum's core** (`momentum/files/ocr.py`) and packs reach it through the SDK (`job.ocr`, `job.ocr_available`), with three settings: `MOMENTUM_OCR_ENABLED` (default on), `MOMENTUM_TESSERACT_CMD` (the binary's path when it isn't on `PATH`) and `MOMENTUM_OCR_LANGUAGES`. **When the binary is missing or OCR is off, scans go straight to vision** — a deployment without Tesseract loses a fallback, never a job.
4. Everything else in ADR-0013 decision 3 stands: no PyMuPDF (AGPL; pypdf splits and pypdfium2 renders, doing the same jobs), no Presidio/spaCy.

## Alternatives considered
| Option | Pros | Cons |
|---|---|---|
| Vision only for scans (ADR-0013 as written) | No system package | Diverges from the proven notebook pipeline; no word positions on scans, so no provenance boxes and no row check there; every scanned page costs a vision call |
| OCR in the cloud (a hosted OCR API) | No binary to install | Sends unmasked financial documents to another service before anything can redact them; a new vendor and contract |
| Tesseract inside the pack | Self-contained | Every pack that needs OCR would configure its own binary path; the server-wide setting belongs in core |

## Consequences
- **Positive:** the scanned-document path matches the notebook's; scans get word-level provenance; fewer vision calls (cost) on clean scans.
- **Negative:** the server image grows (about 30–60 MB with six language packs) and has a system package to keep patched; Windows developers install Tesseract themselves (UB Mannheim build) and set `MOMENTUM_TESSERACT_CMD` if it isn't on `PATH`.
- **Reversal:** `MOMENTUM_OCR_ENABLED=false` returns to vision-only behaviour at once; removing the package from the image does the same.
