# ADR-0011: Files, document parsing and report generation

- **Status:** Accepted (product owner decisions D1–D8, 2026-10-06; this ADR drafted by the AI at S75-00)
- **Date:** 2026-10-06
- **Deciders:** product owner (D1, D4, D6, D7 in the Phase 7.5 spec), AI (drafted)
- **Spec:** `docs/superpowers/specs/2026-10-06-phase-7-5-ai-files-insight-design.md` (§3, §4, §6, §10)

## Context
About 150 people are moving from Asana. They attach Word, Excel (with formulas and macros), CSV, PDF (some scanned), PowerPoint, images, emails and text files, and they need status, close-out and portfolio reports as real documents. Before this phase Mo read only the plain text of PDFs with a text layer, the paragraphs of .docx files and `text/*` files, and Momentum could not produce a document at all.

Three forces shape the design:
1. **Trust in numbers.** People will ask "what's the total of Amount where Status is Overdue?". A model reading a dumped sheet guesses; it must not.
2. **Safety.** Office files can carry macros, external entities, zip bombs; PDFs can carry JavaScript. Momentum runs on the office's Azure tenant with real customer documents.
3. **Cost and privacy.** Nothing should reach the model unless a person asks, and only what that person can see.

## Decision
1. **Nothing changes on upload (D1).** Upload still runs only the existing non-AI text extraction and search indexing. Files are parsed into a structured model **the first time a person asks Mo about them**, as that person, and the parse is cached per attachment (`file_parses`, rows in the storage backend) until the parser version changes. Parsing is a cache, not a user-data mutation, so it records no activity.
2. **Structured reading with tools; numbers from the server (D6).** `momentum/files/` (no AI imports; import-linter enforced) parses every supported format into a `DocumentModel` (outline, text and table blocks, sheets with typed columns, macros as text, email headers, archive listings) with human-readable **locators** (`p3`, `s:Budget!A1:F40`, `slide 4`). Mo reads files through read-only tools (`list_files`, `file_outline`, `read_file`, `read_sheet`, `query_table`, `search_in_file`, `look_at`, `describe_macros`). Any number Mo states about a spreadsheet comes from `query_table` / `read_sheet`, computed in Python over the cached rows. No code sandbox.
3. **Images and scanned pages go to the gateway model (D4)**, rendered by the server (pypdfium2 at 150 DPI, long edge ≤ 1568 px, JPEG q85, EXIF and GPS stripped), only when a person asks, within per-call and per-conversation caps, counted toward usage at `(w*h)/750` tokens. Images ride in a user message after the tool results (OpenAI tool messages can't carry images). `MOMENTUM_LLM_SUPPORTS_VISION=false` turns this off cleanly.
4. **Nothing is ever executed.** Macros are read as text with `oletools.olevba` and described in plain English; formulas are never recalculated (the cached value and the formula text are reported); embedded OLE objects, PDF JavaScript and links are never run or followed. Archives are listed, not recursed. Parses run in a worker thread with a timeout and output caps; zip and XML bombs are rejected before parsing; encrypted files are reported, and passwords are never asked for.
5. **Reports are server-rendered from a spec plus real data (D7).** `momentum/reports/`: `ReportSpec` → a builder per kind using domain queries **as the requester** → a neutral `ReportDocument` → renderers (docx, xlsx, pdf, md, csv). The model writes only the narrative paragraphs, which carry citations; uncited paragraphs are dropped; every renderer marks them "AI-drafted, review before sending". `reports` never imports `ai`: the narrative is a callable injected by `ai/`. Generated files are attachments with `source='generated'` and the spec that made them, so they can be regenerated as a new version and undone.
6. **Built and tested without a gateway.** This phase was built in a cloud session with `MOMENTUM_LLM_MODE=mock`: every AI feature has handwritten fixtures and mock eval cases at 1.0; live-only cases are written for the product owner's run.

**Dependencies** (pure pip wheels, no system packages, locked in `uv.lock`, `pip-audit` clean on 2026-10-06):

| Package | Why |
|---|---|
| `openpyxl` | Read and write .xlsx/.xlsm (cached values and formulas; report workbooks) |
| `xlrd` | Read legacy .xls (read only) |
| `python-pptx` | Read .pptx (slides, tables, notes) |
| `pdfplumber` | PDF text with layout and tables (pypdf stays for metadata and encryption) |
| `pypdfium2` | Render PDF pages to images for vision, without a system Poppler |
| `Pillow` | Images: sniff, size, strip EXIF, re-encode, decompression-bomb guard |
| `oletools` | Read VBA macros statically (olevba); never executes |
| `extract-msg` | Outlook .msg email |
| `striprtf` | .rtf text |
| `defusedxml` | Hardened XML parsing for every OOXML reader (no external entities, no entity expansion bombs) |
| `reportlab` | PDF rendering and chart images for reports |

Fonts: DejaVu Sans (regular, bold) bundled in `momentum/reports/fonts/` with its license (Bitstream Vera / public domain changes) for Unicode coverage in PDFs.

## Alternatives considered
| Option | Pros | Cons |
|---|---|---|
| Dump extracted text into the prompt | Simple | Loses tables and structure; numbers guessed by the model; big prompts; no citations |
| A code sandbox (model writes pandas) | Flexible analysis | A new execution surface on customer files; infrastructure on Azure; hard to audit |
| Parse every file on upload | Instant answers later | Cost and risk on files nobody asks about; contradicts D1 |
| LibreOffice/Poppler for conversion and rendering | Wider format coverage (.doc, .odt) | System packages in the image; a large attack surface; slower cold start |
| Model-written documents (the model emits the .docx) | Fewer moving parts | Numbers not guaranteed; formatting drift; the AI part can't be marked |

## Consequences
- Mo can answer questions about real-world files with citations and exact numbers, and reports are trustworthy documents whose AI parts are visible.
- The image grows by the wheels above (about 40 MB installed) and two fonts (1.4 MB).
- `.doc`, `.odt/.ods/.odp`, `.heic`, `.pages`, `.numbers` are not read (Mo says how to export them); recursive archives, OCR without the model, editing uploaded files and free-form drafting stay on the Later list.
- Reversal: the file tools can be dropped from the tool catalog and the reports endpoints disabled without touching upload, download or search; `file_parses` is a cache and can be truncated at any time.
