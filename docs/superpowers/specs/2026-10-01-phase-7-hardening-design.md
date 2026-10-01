# Phase 7 redesign: Hardening and Asana-ready (design)

> Agreed with the product owner on 2026-10-01 (brainstorming session). This spec drives the Phase 6 exit doc changes and the Phase 7 kickoff. The phase file `docs/roadmap/phase-7.md` is rewritten from it at the Phase 6 exit.

## 1. Why

- **Scale changed.** Momentum was designed for one team of 10–15 people (ADR-0001, vision-and-scope, the Phase 8 locust scenario of 15 users). It will now serve **~150 accounts in one workspace, with 50–75 active at peak**.
- **Audience changed.** Many of the new users are moving off Asana. Their first weeks decide adoption, so the existing features (Phases 0–6) must be close to flawless across every scenario and edge case, UI, backend and AI/agents alike, with the good-to-haves that make it feel finished.
- "Perfect" is made measurable: an edge-case matrix per feature backed by tests, a severity-ranked register with zero open P0/P1 at exit, a 150-user load test meeting budgets, an Asana parity checklist signed off by the product owner, and live AI evals meeting thresholds.

## 2. Roadmap change (applied at the Phase 6 exit)

| New # | Phase | Was |
|---|---|---|
| 6 | Planning and Insight | 6 (finish S6.5.2, S6.5.3, exit first) |
| **7** | **Hardening and Asana-ready** | old Phase 8, much expanded |
| **8** | **Azure deployment and go-live** | old Phase 9 |
| **9** | **Integrations (post-production)** | old Phase 7 |

- **Integrations move after go-live** (product owner: "bring this later even after set into production, it should work"). Slack comes first when that phase starts; Outlook, email-to-task and outgoing webhooks follow later. Nothing is deleted.
- **Go-live must not depend on integrations:** remove "Slack app installed; digest test received" from the go-live checklist and the Slack install from S9.3.3; keep `/webhooks/*` in the planned Easy Auth exclusions so enabling an integration later is a settings change and a deploy, not infra rework.
- **Later list** (no phase yet): mobile / PWA (old S8.1, product owner: "future"), Outlook calendar, email-to-task, outgoing webhooks, code-host integration.
- **Target platform for Phase 7:** desktop browsers (current Chrome and Edge, laptop widths and up). No phone layout work.
- Record the change in `roadmap.md`, the phase files (renumbered), the STATUS "Plan changes" log, `model-guide.md` §4, and a new ADR (§4 below). Update the 10–15 user wording in `vision-and-scope.md` and `end-to-end-guide.md`.

## 3. Phase 7 epics

### E7.0 Audit (read-only)
- For every feature in Phases 0–6, an **edge-case matrix**: empty / huge, concurrent edits by two people, every role (admin, member, guest, collaborator, agent, API token), deleted or archived parents, timezone and DST boundaries, long and unicode text, offline and realtime reconnect, undo of every mutation, keyboard-only use, accessibility basics. AI features add: AI unavailable, slow or partial streaming, prompt injection in user content, permission leakage (asking about what you can't see), budget exhaustion.
- **Exploratory passes:** a Playwright click-through of every screen and state, and the product owner's "100+ questions/actions against the real gateway" run (instruction of 2026-09-26), run on the product owner's machine.
- **Outputs:** `docs/progress/hardening-register.md` with one row per finding (id, area, phase/slice, severity, scenario, expected vs actual, fix slice) and severity **P0** broken / data loss / security or permission leak, **P1** wrong or confusing, **P2** polish, **P3** nice-to-have; plus the **Asana parity checklist** (feature → have / partial / missing → decision).
- **Gate:** the product owner reviews the register and the parity checklist; every P2/P3 deferral and every parity "missing → later" is signed off.

### E7.1 Scale to 150
- New ADR updating ADR-0001's scale assumption: one App Service, worker may run as a separate process, DB pool sizing, realtime fan-out limits, per-user AI rate limits and budgets sized for 150 people.
- Load test (locust, replacing the old 15-user scenario): 150 accounts, 75 concurrent, 50k-task workspace with comments, fields, dependencies and agent runs.
- Budgets: API p95 < 150 ms reads, < 300 ms writes; realtime delivery < 1 s p95; no pool exhaustion; job queue keeps up with agent and notification load; shell JS ≤ 300 KB gz (carried from old S8.2).
- Fix what it exposes (known: per-subtask ancestor queries on Home and My Tasks).

### E7.2 Fix slices
- All P0 and P1 findings, grouped by area into slices; P2 unless deferred with sign-off. Each fix ships with the test that proves it.

### E7.3 AI and agent hardening
- Expand evals: edge cases, adversarial and injection inputs, cross-permission questions, concurrent agent runs for many users, budget behaviour at 150 users, degraded gateway.
- Live gateway run on the product owner's machine; every bucket meets its threshold before exit.

### E7.4 Asana-ready
- **Custom-field reporting (must-have):** filter, sort and group by custom fields in all views, across projects (My Tasks, search, portfolios) and in dashboard charts (`QuerySpec`).
- **Full Asana import (must-have):** comments, attachments, custom fields, dependencies, subtasks, followers, sections, tags, milestones, approvals where mappable; dry-run report with counts and anything unmapped; idempotent re-run.
- **Email notifications:** immediate emails for assignments and mentions, a daily digest, per-user preferences; behind an email-sender interface (logged locally in dev; office mail relay in production, a new Phase 8 go-live prerequisite to ask IT for).
- **Familiarity:** Asana-compatible keyboard shortcuts where they don't conflict, Asana terms where ours differ, and a "Coming from Asana?" onboarding.

### E7.5 Carried from the old Phase 8
- Security review (OWASP ASVS L1, route-enumeration authz test, CSRF, uploads, rate limits, security headers).
- Accessibility (axe in Playwright on key pages, keyboard-only journeys, focus management).
- Export / import round-trip (lossless on the seed workspace).
- Admin completeness: invite, role change, disable, transfer ownership, teams admin, jobs panel, audit view (essential at 150 people).
- Backup / restore rehearsal.

## 4. Order and models

| # | Step | Model |
|---|---|---|
| 0 | Finish S6.5.2, S6.5.3, Phase 6 exit (applies §2 doc changes + ADR) | per model-guide; exit Opus |
| 1 | Phase 7 kickoff + E7.0 audit | Opus |
| 2 | Register review with the product owner | — |
| 3 | E7.1 scale | Opus |
| 4 | E7.2 P0 fixes | Opus |
| 5 | E7.4 Asana-ready (importer on Opus) | Sonnet / Opus |
| 6 | E7.2 P1/P2 fixes | Sonnet |
| 7 | E7.3 AI and agent hardening + live run | Opus |
| 8 | E7.5 security, a11y, export/import, admin, backup | mixed |
| 9 | Phase 7 exit | Opus |

Working rules are unchanged: one slice at a time, `make check` green, docs in the same slice, commit and push each. Stop for the register review, permission-semantics changes, and data-rewriting migrations. Live checkpoints on the product owner's machine: after the audit, after E7.3, at exit.

## 5. Exit criteria

- Zero open P0/P1 in the register; every deferred item signed off.
- Journeys J1–J12 pass, plus new journeys for the full Asana import, custom-field reporting and email notifications.
- The 150-user load test meets the E7.1 budgets.
- axe: no serious violations on key pages.
- Live evals: every bucket meets its threshold.
- Export → import round-trip lossless; backup restore rehearsed.
