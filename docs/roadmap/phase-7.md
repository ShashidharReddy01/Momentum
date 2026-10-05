# Phase 7: Hardening and Asana-ready (Local)

> **Re-planned 2026-10-01 (product owner).** Was "Phase 8: Hardening". Design: `docs/superpowers/specs/2026-10-01-phase-7-hardening-design.md`. Integrations moved after go-live (Phase 9), Azure go-live is Phase 8. Starts after Phase 6.5 (UI/UX revamp) exits.

**Goal:** Momentum will serve **~150 accounts in one workspace (50–75 active at peak)**, many moving off Asana. Before go-live, everything already built (Phases 0–6.5) must be close to flawless in every scenario and edge case, UI, backend, AI and agents alike, with the good-to-haves that make it feel finished. "Perfect" is made measurable: an edge-case matrix per feature backed by tests, a severity-ranked register with zero open P0/P1 at exit, a 150-user load test within budget, an Asana parity checklist signed off by the product owner, and live AI evals at threshold.

**How this phase runs (product owner, 2026-10-04):** "fix everything": every register finding is fixed, **P3 nice-to-haves included**; no deferrals. The product owner delegated the review gates (register triage, the scale ADR) to the AI and asked not to be consulted until the phase is done; every such decision is recorded in the register or STATUS for later review. Live gateway runs are approved. New dependencies approved: locust and security-audit tools (dev only). **Email notifications moved to Later** ("no need email and all, all later").

**Target platform:** desktop browsers (current Chrome and Edge, laptop widths and up, the Phase 6.5 viewports). Native/PWA mobile is on the Later list.

**Exit criteria:**
- Zero open findings in the hardening register (P0–P3).
- Journeys J1–J12 pass, plus new journeys for the full Asana import and custom-field reporting.
- The 150-user load test meets the E7.1 budgets.
- axe: no serious violations on key pages (building on Phase 6.5's WCAG 2.2 AA pass).
- Live evals: every bucket meets its threshold (incl. the new edge-case and injection cases).
- Export → import round-trip lossless on the seed workspace; backup restore rehearsed.

---

## E7.0 Audit (read-only, first)

For every feature in Phases 0–6.5, an **edge-case matrix**: empty / huge, two people editing at once, every role (admin, member, guest, collaborator, agent, API token), deleted or archived parents, timezone and DST and month boundaries, long and unicode text, offline and realtime reconnect, undo of every mutation, keyboard-only use. AI features add: AI unavailable, slow or partial streaming, prompt injection in user content, permission leakage (asking about what you can't see), budget exhaustion.

**Exploratory passes:** a Playwright click-through of every screen and state on the showcase seed, and the product owner's "100+ questions/actions against the real gateway" run (instruction of 2026-09-26) on the product owner's machine.

**Outputs:** `docs/progress/hardening-register.md` (one row per finding: id, area, phase/slice, severity, scenario, expected vs actual, fix slice; **P0** broken / data loss / security or permission leak, **P1** wrong or confusing, **P2** polish, **P3** nice-to-have) and the **Asana parity checklist** (extends `docs/product/asana-vs-momentum.md`: feature → have / partial / missing → decision). Phase 6.5's audit covers visual and layout issues; this one covers behaviour.

**Gate:** delegated (see "How this phase runs"): every finding is fixed; parity gaps are either closed in this phase or recorded with a reason (e.g. native mobile apps, integrations: product-owner decisions to do later).

**Already known (feed into the register):** the dashboard chart editor dropped filters it has no control for (fixed 2026-10-01); a usage-report test failed on the 1st of every month (fixed 2026-10-01).

## E7.1 Scale to 150 (was S8.2)

| Slice | Scope | AC | Size |
|---|---|---|---|
| S7.1.1 Scale ADR | Update ADR-0001's 10–15 user assumption: one App Service, worker as a separate process if measured necessary, DB pool sizing, realtime fan-out limits, per-user AI rate limits and budgets sized for 150 people | ADR accepted by the product owner | S |
| S7.1.2 Load test and fixes | Query plans for the top 20 endpoints, missing indexes, N+1 audit (known: per-subtask ancestor queries on Home and My Tasks), bundle analysis; **locust: 150 accounts, 75 concurrent, a 50k-task workspace** with comments, fields, dependencies and agent runs | API p95 < 150 ms reads, < 300 ms writes; realtime delivery < 1 s p95; no pool exhaustion; the job queue keeps up; shell JS ≤ 300 KB gz | L |

**As built (2026-10-05).** S7.1.1: ADR-0010 (amends ADR-0001): one image with `MOMENTUM_WEB_WORKERS=4` for ~150 people, a connection budget (4 × (5 + 5 + 2) = 48, warned above 80% of `max_connections`), the embedded job worker kept (it kept up), per-class latency budgets (item reads < 150 ms, list views < 400 ms, writes < 300 ms, realtime < 1 s), `MOMENTUM_AI_USER_CALLS_PER_HOUR` (200), and agent budgets sized for ~150 people (H32). S7.1.2: `momentum seed --scale` (150 people, 60 projects, ~50k tasks), `tools/load/locustfile.py`, `tools/load/realtime_probe.py`, `tools/load/serve.sh`. At 75 concurrent: aggregate p95 190 ms with every class within budget, realtime 400/400 at p95 193 ms, no pool exhaustion, the queue kept up; shell JS 291 KB gzip (H6). Fixes: H35–H40, including a lost-event bug in realtime dispatch (H39). Numbers and method: `performance.md` "Scale to ~150 people". **Plan change:** the single "reads < 150 ms" budget became per-class budgets (list views aggregate hundreds of rows and refresh in the background), and the budgets are re-checked on staging before go-live (phase-8.md checklist).

## E7.2 Fix slices

Every register finding (P0 first, then P1, P2, P3), grouped by area into slices. Each fix ships with the test that proves it. Slices are added to this file once the register exists.

## E7.3 AI and agent hardening

| Slice | Scope | AC | Size |
|---|---|---|---|
| S7.3.1 Eval expansion | Edge-case, adversarial and injection inputs for every AI feature and agent; cross-permission questions; concurrent agent runs for many users; budget behaviour at 150 users; a degraded gateway | New cases pass in mock; injection fixtures can't trigger unauthorized writes | M |
| S7.3.2 Live run | `EVALS_LIVE=1 make evals` on the product owner's machine; fix what it finds | Every bucket meets its threshold | M |

## E7.4 Asana-ready

| Slice | Scope | AC | Size |
|---|---|---|---|
| S7.4.1 Custom-field reporting (must-have) | Filter, sort and group by custom fields in list, board and calendar, across projects (My Tasks, search, portfolios), and in dashboard charts (`QuerySpec`: field filters, number/date fields) | A journey filters and charts by a custom field across two projects | L |
| S7.4.2 Full Asana import (must-have) | Comments, attachments, custom fields, dependencies, subtasks, followers, sections, tags, milestones, approvals where mappable; a dry-run report with counts and anything unmapped; idempotent re-run (extends S2.7.1, `docs/integrations/asana-import.md`) | Round-trip on a synthetic Asana export: counts match, the report lists every skipped item | L |
| S7.4.4 Familiarity | Asana-compatible keyboard shortcuts where they don't conflict, Asana terms where ours differ, a "Coming from Asana?" onboarding | Shortcut sheet lists them; onboarding reachable from Home | S |

## E7.5 Production quality (was Phase 8)

| Slice | Scope | AC | Size |
|---|---|---|---|
| S7.5.1 Export / import (was S8.3) | `momentum export` (versioned JSON bundle + optional files, ids preserved) and `momentum import` (into an empty workspace or schema); admin UI trigger for export | Round-trip test: counts and checksums equal | M |
| S7.5.2 Security review (was S8.4) | OWASP ASVS L1 checklist: authz on every endpoint (automated test that enumerates routes and asserts auth), CSRF, upload validation (type, size, AV hook optional), rate limits (login-adjacent, public forms, AI endpoints), security headers (CSP with nonce, HSTS in prod, frame-ancestors), dependency audit (`pip-audit`, `pnpm audit`), secrets scan, prompt-injection test suite for agents (malicious task text/comment/email fixtures) | No high findings; injection fixtures can't trigger unauthorized writes | M |
| S7.5.3 Accessibility (was S8.5) | Keyboard-only walkthrough of all journeys; axe in Playwright on key pages; screen-reader labels for list/board/pane; focus management audit (on top of Phase 6.5's pass) | No serious violations | S |
| S7.5.4 Admin completeness (was S8.6) | Members (invite, role, disable, transfer ownership), teams admin, AI settings, agents policy, integrations status, background jobs panel (failed jobs, retry), audit view (activity search for admins). Essential at 150 people | Admin can do everything without DB access | M |
| S7.5.5 Backup/restore rehearsal (was S8.7) | `pg_dump -n momentum` + files → restore into a fresh environment script; document | Restore rehearsal succeeds | S |

## Order and models

Kickoff + E7.0 (Opus) → register review with the product owner → E7.1 (Opus) → E7.2 P0 fixes (Opus) → E7.4 (Sonnet; the importer on Opus) → E7.2 P1/P2 (Sonnet) → E7.3 (Opus) → E7.5 (mixed) → exit (Opus). Live checkpoints on the product owner's machine: after the audit, after E7.3, at exit.

## Later (no phase yet)

PWA / mobile (was S8.1; product owner 2026-10-01: "future"), email notifications (was S7.4.3; product owner 2026-10-04: "all later"), Outlook calendar, email-to-task, outgoing webhooks, code-host integration (the last four are in Phase 9's backlog).
