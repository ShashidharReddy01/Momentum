# Bernie: the invoice agent

**Not built yet** — this is the Phase 7.6 S76-00 packaging skeleton. See
`docs/roadmap/phase-7.6.md` (S76-01 onward) and
`docs/superpowers/specs/2026-10-06-phase-7-6-agent-platform-bernie-design.md` §9 for what Bernie
will do and how. `docs/reference/coap-invoice-pipeline/README.md` is the source Bernie ports.

Once built: Bernie reads invoices (PDF, scans, images, e-invoices, zips), checks every number
with deterministic code (never the model), asks a person when something doesn't add up, and
routes the result for approval. See `docs/agents/bernie.md` (written in S76-13) for the
user-facing guide, and this pack's own tests for the ground truth of what it actually does.
