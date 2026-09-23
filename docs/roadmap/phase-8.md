# Phase 8: Hardening (Local)

**Goal:** production quality before deployment: performance, security, accessibility, data portability, and admin completeness.

**Exit criteria:** perf budgets met; security checklist complete with no high findings; axe shows no serious violations on key pages; export → import round-trip is lossless on the seed workspace.

| Slice | Scope | AC | Size |
|---|---|---|---|
| S8.1 PWA and mobile | Manifest, service worker (static assets only, no API caching of private data), responsive My Tasks/Inbox/Task pane, touch DnD fallbacks | Installable; usable at 390px width | M |
| S8.2 Performance pass | Query plans for top 20 endpoints, missing indexes, N+1 audit, bundle analysis and splitting, locust 15-user scenario on a 20k-task workspace | p95 < 150 ms API; shell JS ≤ 300 KB gz | M |
| S8.3 Export / import | `momentum export` (versioned JSON bundle + optional files, ids preserved) and `momentum import` (into an empty workspace or schema); admin UI trigger for export | Round-trip test: counts and checksums equal | M |
| S8.4 Security review | OWASP ASVS L1 checklist: authz on every endpoint (automated test that enumerates routes and asserts auth), CSRF, upload validation (type, size, AV hook optional), rate limits (login-adjacent, public forms, AI endpoints), security headers (CSP with nonce, HSTS in prod, frame-ancestors), dependency audit (`pip-audit`, `pnpm audit`), secrets scan, prompt-injection test suite for agents (malicious task text/comment/email fixtures) | No high findings; injection fixtures can't trigger unauthorized writes | M |
| S8.5 Accessibility | Keyboard-only walkthrough of all journeys; axe in Playwright on key pages; screen-reader labels for list/board/pane; focus management audit | No serious violations | S |
| S8.6 Admin completeness | Members (invite, role, disable, transfer ownership), teams admin, AI settings, agents policy, integrations status, background jobs panel (failed jobs, retry), audit view (activity search for admins) | Admin can do everything without DB access | M |
| S8.7 Backup/restore runbook (local rehearsal) | `pg_dump -n momentum` + files → restore into a fresh environment script; document | Restore rehearsal succeeds | S |
