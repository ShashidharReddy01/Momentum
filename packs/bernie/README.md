# Bernie: the invoice agent

Reads invoices (PDF, scans, images, Factur-X/ZUGFeRD/XRechnung/UBL e-invoices, zips, emails) into
checked invoice records, one per invoice, line by line, ready for the Records tab and the Excel
export. A faithful port of the COAP notebook's pipeline (`docs/reference/coap-invoice-pipeline/`)
onto Momentum's agent platform (ADR-0012, ADR-0013, ADR-0014).

- `momentum_pack_bernie/pipeline.py`: the job, step by step (spec §9.3).
- `ingest.py`, `einvoice.py`, `read.py` (text → OCR → vision), `vendors.py`, `extract.py`,
  `locate.py`, `checks_math.py`: one stage each, no model calls except in `extract` and the
  vendor fallback.
- `prompts/`: the versioned prompts; `evals/`: the eval cases; `quality.py`: how extraction is
  scored against ground truth.
- `tests/`: the pure tests and `tests/synth/build.py`, the synthetic invoice generator (fictional
  vendors only); the tests that need a database are `apps/api/tests/test_bernie_*.py`.

Real invoices never enter this repository.
