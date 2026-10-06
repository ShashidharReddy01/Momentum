# Files: what Momentum reads, how, and what it never does

> Phase 7.5 (ADR-0011, spec `docs/superpowers/specs/2026-10-06-phase-7-5-ai-files-insight-design.md` §4). Code: `apps/api/momentum/files/`.

## When a file is read

**Never on upload** (D1). Uploading runs only the old non-AI text extraction for search (`jobs/attachments.py`). A file is parsed the first time Mo needs it because a person asked about it, as that person, and only if they can see it (callers check visibility before calling the cache). The parse is cached in `file_parses` (the model, in the database) and the storage backend (sheet rows, gzipped JSON at `<workspace>/parses/<file>/v<parser version>.json.gz`) until `PARSER_VERSION` changes. Deleting a file drops its parse; an undone delete parses again on demand. A parse is a cache, not a change to anyone's data, so it records no activity.

## What a parse produces

A `DocumentModel` (`files/model.py`): the file header (kind, size, pages / sheets / slides, encrypted, truncated, warnings), an **outline** (headings, sheets, slides), **blocks** (text, tables, image references) with human-readable **locators**, **sheet summaries** (header guess, typed columns, row count, formulas with cached values, named ranges, merged cells, hidden flag, chart count), **macros** (as text with plain-English flags), **email** headers and attachment names, and **archive** listings.

Locators: `p3` (page 3), `p2 table 1`, `s:Budget` (a sheet; ranges as `s:Budget!A1:F40`), `slide 4`, `slide 4 notes`, `table 2` (a Word table), `§ Scope > Out of scope` (the section under those headings), `header (section 1)`, `comment 0`, `footnote 1`, `line 12`, `body` (an email).

## Formats

| Family | Formats | Library | Extracted | Limits / notes |
|---|---|---|---|---|
| Word | .docx, .docm, .dotx | python-docx | Paragraphs with heading levels, tables, headers and footers, comments, footnotes, inline pictures; .docm macros (olevba) | A .docm/.dotx is opened through an in-memory copy with the plain content type |
| Rich text | .rtf | striprtf | Text paragraphs | |
| Legacy Word | .doc | none | Warning: "save it as .docx and attach it again" | Not read |
| Excel | .xlsx, .xlsm, .xltx | openpyxl (values and formulas loaded separately) | Every sheet: header guess, typed columns, rows (cached values), formulas as text beside their cached values (first 500 listed), named ranges, merged cells flattened, hidden sheets, chart count; .xlsm macros | Formulas are **never recalculated**: a workbook saved without results says so |
| Legacy Excel | .xls | xlrd | Sheets and values | No formulas from this format (warning) |
| CSV / TSV | .csv, .tsv, `text/csv` | stdlib `csv` (sniffed delimiter) | One sheet, typed columns | UTF-8 (BOM or not), UTF-16 with BOM, else Windows-1252; cells starting `= + - @` are text (warning) |
| PowerPoint | .pptx | python-pptx | Slide titles (outline), text frames, tables, speaker notes, pictures | .ppt is not read |
| PDF | .pdf | pdfplumber (text, tables), pypdf (encryption) | Per page: text and tables; scanned pages (< 30 characters and a picture over half the page) become image references for vision | Owner-password-only PDFs open; user-password PDFs are `encrypted` |
| Images | .png, .jpg, .gif, .webp, .bmp, .tiff | Pillow | One image reference with its size | ≤ 40 megapixels, checked from the header |
| Text | .txt, .md, .log, .json, .xml, .yaml, .html | stdlib, defusedxml | Text; Markdown headings as the outline; JSON and XML pretty-printed (200,000 characters); HTML as text without scripts or styles | XML through defusedxml (no entities, no external references) |
| Email | .eml, .msg | stdlib `email`, extract-msg | Headers, the plain body (an HTML-only body as text), attachment names | Attachments inside aren't opened |
| Archive | .zip | stdlib `zipfile` | Entry list (first 500) | No recursion: "attach the file inside on its own" |
| Not yet | .odt/.ods/.odp, .heic/.heif, .pages, .numbers, .key, .ppt | none | Warning: "<type> can't be read yet: export it as PDF, Word or Excel" | |

## Table queries

`files/tables.py` runs a `TableQuery` (filters `eq ne lt lte gt gte contains in empty not_empty`, ≤ 2 group-by columns, aggregates `count sum avg min max distinct_count`, sort, limit ≤ 200; `extra='forbid'`) in Python over the cached rows. Columns are named by header text (case-insensitive) or letter. Each column is typed once (`files/values.py`): numbers with the decimal separator inferred **per column** (`1.234,50` vs `1,234.50`), `(1,234)` as negative, `12%` as 0.12, currency signs ignored; dates in ISO and day/month forms (day-first unless the column shows otherwise); booleans (true/false, yes/no). Errors name the columns that exist. A sheet cut at parse time marks every result `truncated` with a note.

## Limits

| Limit | Value | Where |
|---|---|---|
| Parse time | `MOMENTUM_FILE_PARSE_TIMEOUT_S` (20 s), in a worker thread; then "That file took too long to read" | `cache.parse_with_timeout` |
| Rows per sheet | `MOMENTUM_FILE_PARSE_MAX_ROWS` (200,000) and 100 columns; beyond: truncated | `parsers/sheets.py` |
| Text per file | 2 MB; beyond: truncated | `safety.cap_text` |
| Unzipped size | 250 MB total, ratio ≤ 100:1 (from the central directory, before anything is decompressed) | `safety.check_zip` |
| XML in OOXML | No `<!DOCTYPE` or `<!ENTITY` in any part (first 4 KB of each) | `safety.check_ooxml_xml` |
| Image size | 40 megapixels | `safety.check_image_header` |
| Rendering for vision | PDF pages at 150 DPI (pypdfium2), long edge ≤ 1568 px, JPEG q85; a fresh JPEG with no metadata (EXIF and GPS dropped) | `render.py` |

## What is never done

- **Nothing is executed.** Macros, formulas, embedded OLE objects, PDF JavaScript, forms and links are read as data or ignored. No process is started and no Office automation is used (`test_file_safety.py::test_nothing_is_ever_executed`).
- Passwords are never asked for, guessed or stored: an encrypted file is reported as `encrypted`.
- Archives are never unpacked beyond their listing; attachments inside emails are never opened.
- File content is **data, never instructions**: hostile text in a document, a cell, a macro comment or an image is reported, not obeyed (prompt rules and evals from S75-03).

## Samples for tests, evals and the seed

`momentum/files/samples/` builds every sample file from readable Python at run time (no binaries in the repository): Word (with a hostile paragraph, comments, a picture), a .docm and an .xlsm with real VBA projects (`samples/ole.py`: an OLE compound-file writer and an MS-OVBA project writer), workbooks with cached formula results (patched into the XML, as Excel saves them) and one never recalculated, a BIFF8 .xls, a semicolon CSV with comma decimals and a formula-injection cell, a .pptx, PDFs (text layer with a ruled table, scanned, encrypted), PNG/JPEG (with EXIF), .eml and .msg, .rtf, .zip, an encrypted .xlsx, and zip and XML bombs (built in memory only). `tests/fixtures/files/build.py` re-exports them for tests.
