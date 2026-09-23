# STATUS

> Updated by the AI at the end of every slice and every session. The human confirms "done" after trying the slice.

## Current focus
- **Phase:** 0: Foundations. **Complete** except the items noted below
- **Next slice:** S1.1.2 Projects
- **Model:** **Opus 5.5** for all of Phase 1 (and Phases 3, 5), per product owner decision; see `docs/process/model-guide.md`
- **Blockers:** the GitHub repo `shashidharreddy01/momentum` must be created and connected so the code can be pushed

## Handoff notes (latest session: 2026-09-23, Phase 1)
- Phase 1 kickoff written (`docs/roadmap/phase-1-kickoff.md`). Project/team access rules live in `momentum/domain/access.py`.
- Build container: Postgres must be restarted at session start (`su postgres -c "pg_ctl -D /home/user/.pgdata -o '-p 5432 -k /tmp' start"`).

## Handoff notes (Phase 0)
- Built in a cloud container: native Postgres 16 + pgvector 0.6 (no Docker there). Docker Compose is provided for local machines.
- `make check` is green: backend 35 tests (ruff, mypy --strict, import-linter), frontend 10 tests (eslint, tsc, prettier, vitest).
- The app runs end to end: dev login → Home; ⌘K palette; ⌘J Ask Mo panel; `/dev/ui` gallery in light and dark.
- Not verified here: `docker build` of `infra/docker/Dockerfile` (no Docker daemon in the build container). Verify on first local run.

## Open questions
| # | Question | Needed by | Status |
|---|---|---|---|
| 1 | LiteLLM model aliases for Claude (fast/default/smart) and Cohere v3 variant (english/multilingual) | Phase 3 | open |
| 2 | Office Azure constraints (region, networking, Entra app registration owner) | Phase 9 kickoff (ask during Phase 7) | open |
| 3 | Target host project for plugging in (stack/auth) | Before Phase 8 | open (INTEGRATION_GUIDE.md covers all modes) |

## Progress

### Phase 0: Foundations
- [x] S0.1.1 Monorepo scaffold
- [x] S0.1.2 Dev environment and Docker image. Compose + Dockerfile written; **docker build not yet verified**
- [x] S0.1.3 Quality gate (`make check`; incl. stale API-types check)
- [x] S0.1.4 Settings, logging, errors (OTEL exporter deferred to Phase 9 as planned)
- [x] S0.1.5 Database core and job queue (Procrastinate schema inside the Momentum schema)
- [x] S0.2.1 AuthProvider + dev mode + /me
- [x] S0.2.2 Easy Auth provider + simulator
- [x] S0.2.3 Identity resolution and bootstrap admin (link-by-email tested)
- [x] S0.2.4 Permissions skeleton
- [x] S0.3.1 Design tokens, fonts, base components (+ `/dev/ui` gallery)
- [x] S0.3.2 Layout shell + routing + command palette skeleton

### Phase 1: Core tasks MVP
- [x] S1.1.1 Teams (+ undo registry, `POST /undo`, `GET /users`, PeoplePicker, InlineText, undo toasts) · [ ] S1.1.2 Projects · [ ] S1.1.3 Project members and roles
- [ ] S1.2.1 Sections · [ ] S1.2.2 Tasks · [ ] S1.2.3 Assignee and dates · [ ] S1.2.4 DnD, multi-select, bulk · [ ] S1.2.5 Filter/sort/group · [ ] S1.2.6 List performance
- [ ] S1.3.1 Pane · [ ] S1.3.2 Subtasks · [ ] S1.3.3 Followers
- [ ] S1.4.1 Comments · [ ] S1.4.2 Activity feed · [ ] S1.4.3 Undo
- [ ] S1.5.1 My Tasks · [ ] S1.5.2 Home

### Phases 2–9
Tracked in their phase files; copy the slice list here at each phase kickoff.

## Plan changes log
| Date | Change | Reason |
|---|---|---|
| 2026-09-23 | Backend tests use a real Postgres via `MOMENTUM_TEST_DATABASE_URL` + truncate-per-test, instead of testcontainers + SAVEPOINT | Build environment has no Docker; services commit normally, which keeps tests realistic |
| 2026-09-23 | Migrations live inside the package (`momentum/migrations`) | Hosts that install the package get migrations too (embedding) |
| 2026-09-23 | App wiring moved to `momentum/api/` (deps, runtime, system) | Keeps `core` free of outer-layer imports (import-linter) |
| 2026-09-23 | Queue names prefixed `momentum_`; NOTIFY channel `<schema>_events` | Coexist with a host that also uses Procrastinate/NOTIFY |
| 2026-09-23 | Base path handled by React Router `basename` (no custom link wrapper) | Simpler; tested |
| 2026-09-23 | Added `docs/integrations/asana-import.md` and root `INTEGRATION_GUIDE.md` | Asana data migration spec; guide for plugging into another project |
| 2026-09-23 | Visual style changed to neutral + one blue accent, Inter only; tokens renamed to `canvas`/`sidebar`/`surface`/`surface-2`/`accent` (ADR-0005 amendment) | The inherited editorial style read as generic AI design; cheap to fix before Phase 1 |
| 2026-09-23 | Final themes: Light = Paper (cream + ink accent), Dark = Graphite (charcoal + lime); palette picker removed (ADR-0005 amendment 2) | Blue/white rejected by the product owner; chosen from five options shown on the real UI |

## Phase retros
### Phase 0 (2026-09-23)
- Went well: portability tests from day one; the Easy Auth simulator exercises the real parser locally.
- Watch: bundle is 178 KB gz; keep the lazy-loading discipline in Phase 1 (editor, DnD).
- Lesson moved to docs: never `pkill -f` with a pattern that matches your own shell command (runbook troubleshooting).
