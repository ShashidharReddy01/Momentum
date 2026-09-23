# STATUS

> Updated by the AI at the end of every slice and every session. The human confirms "done" after trying the slice.

## Current focus
- **Phase:** 2: Daily-Use Parity (in progress; started without a Phase 1 sign-off gate, per explicit product-owner instruction to proceed autonomously — see plan-changes log)
- **Next slice:** S2.2.1 Board view
- **Model:** Opus 5.5 for Phase 1; **switched to Sonnet 5 mid-Phase-2** by product owner instruction (Phase 2 was never designated an Opus-only phase — see `docs/process/model-guide.md`)
- **Blockers:** none

## Handoff notes (latest session: 2026-09-23/24, Phase 2 start)
- Product owner said (asleep, unavailable for questions): proceed through Phase 2 at the AI's own pace, no permission-asking; note blockers/decisions here instead of stopping.
- **S2.1.1 Realtime (done):** `momentum/realtime/{hub,dispatch,listener,router}.py`. Design: each app process runs its own `Hub` (in-process pub/sub) plus a `LISTEN momentum_events` background task; on every NOTIFY it re-reads `events_outbox` rows above *that process's own* cursor (never filtered by `dispatched_at`, which is a shared, first-writer-wins "seen by someone" marker, not a per-reader lock — see dispatch.py's docstring) and fans them out locally. `GET /ws`: one-channel-per-message subscribe/unsubscribe (`{"op":"subscribe","channel":"project:<id>","since":<id>}`), permission-checked by reusing `domain/access.py`'s existing visibility functions (not re-derived), backlog replay per channel (JSONB `?` containment query, capped at 500, else `resync`), server-initiated ping/pong (45s timeout), a durable `consumer_offsets(consumer, last_event_id)` cursor table (generic — realtime uses `ws:<user_id>`, later job consumers get their own key on the same table). Migration 0007. Tested against real Postgres LISTEN/NOTIFY across two separate app instances (not a same-process shortcut) in `tests/test_realtime.py`; AC "two browsers see an update within 1s" passes with room to spare. `docs/architecture/realtime-jobs-events.md` updated to match what actually shipped (the Phase-0 sketch had batched subscribes and a separate replay message; simplified once real). Tests default `realtime_enabled=False` (most don't need a LISTEN connection open); the new test files turn it on explicitly.
- Deliberate simplification, flagged for later: a subscribed channel's permission is checked once, at subscribe time, not re-validated on every subsequent event. Someone who loses access to a project mid-connection keeps receiving its events until they reconnect. Fine for 10-15 users; revisit if that ever matters.
- Bug caught only by actually running the test (not by reasoning about the code): the replay condition was `since > 0`, silently skipping backlog replay whenever a client asked for `since=0` ("everything"). Fixed to `since >= 0`.

- **S2.1.2 Realtime frontend client (done):** `RealtimeClient` (reconnect+backoff+jitter, ref-counted per-channel subscriptions, replay-since-last-id on reconnect, cursor dropped on resync/overflow), `useChannel` hook, `RealtimeProvider` (mounted inside `AuthGate`, so it connects only once signed in and tears down on sign-out), `ReconnectingBanner` (shown only on an actual mid-session drop). `handlers.ts` prefers in-place `syncTask`/`dropTask` patches (Phase 1's own mutation helpers — no flicker) over `invalidateQueries`, used only where there's no cheaper way to know the new state. `mine.ts` + a one-line hook in `lib/undo.ts` suppress the actor's own echo for free across every mutation that already reports an `activity_id` to the undo stack (which is nearly all of them) — verified with a real two-browser-tab test against the real backend: **zero** extra network requests after the actor's own edit. Two small, well-justified backend additions made alongside this (not scope creep — both directly serve "list order stays consistent" and "no flicker" in the AC): `channels()` now always includes a subtask's parent's channel too (a rename/complete/delete on a subtask used to reach only the subtask's own channel, so an open parent pane's subtask list and ↳ counts never updated live — now they do), and every WS delivery is labeled with which channel it matched (`to_message(row, channel)`), since one change can match more than one of a connection's subscriptions and needs to be routed, not guessed at, client-side. Verified live: two real browser tabs, a rename and a completion, both showing up in the other tab (list row, open pane, and activity feed) within under a second, no reload.
- **Known gap, not silent:** bulk operations (`POST /tasks/bulk`, multi-task move) don't expose per-row `activity_id`s to the frontend yet (only a shared `batch_id`), so a bulk action's own realtime echo isn't suppressed — costs one harmless extra refetch, not incorrect data. Fix if it ever matters: add per-row ids to the bulk mutation's response, or have the frontend register the `batch_id` too and have dispatch.py also stamp `batch_id` onto outbox rows.
- **Bundle size watch (Phase 1 retro flagged this):** production JS grew ~37 KB gzipped with the realtime client wired into 4 always-eager screens (726→838 KB total, 222→258 KB gzip). Not urgent at 10-15 users; code-split if Board/Calendar push it further.

## Handoff notes (2026-09-23, Phase 1)
- Phase 1 kickoff written (`docs/roadmap/phase-1-kickoff.md`). Project/team access rules live in `momentum/domain/access.py`.
- Build container: Postgres must be restarted at session start (`su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /home/user/.pgdata -o '-p 5432 -k /tmp' -l /tmp/pg.log start"`). The web app uses **pnpm** (npm fails on the pnpm lockfile).
- S1.2.3: dates are parsed in the **browser's** timezone (chrono-node, `lib/dates.ts`); the server derives `due_on` from `due_at` in the user's stored timezone only when the client omits it (the UI always sends both). Rows are focusable: `A` / `M` / `D` / `Enter`. 

- S1.2.4: order keys are generated by bisection (`keys_between`) and a section is **rebalanced** automatically when a key would exceed 32 chars (repeated inserts at one spot); rebalancing includes deleted tasks so restores still sort. List mutations that change order run through a serial queue in `useTaskMutations`, and a response only lands if it's the latest for that task (no snap-back on rapid moves). Drag and drop is verified in a real browser (single, multi, cross-section, reload, undo).

- S1.2.5: the list filters/sorts/groups **client-side** from the full incomplete list already in cache (instant, no refetch); the API supports the same filters for other clients (AI, integrations). Completed tasks are paged (100) so filters apply to the loaded pages.

- S1.3.1: descriptions are Tiptap JSON validated by `core/richtext.py` (allow-listed nodes/marks, safe link protocols, size/depth caps). Saves send `description_base` (the `description_hash` they started from) so only a concurrent *description* edit conflicts. The client keeps a device draft (`momentum.draft.description.<task>`) from the first keystroke until the server confirms; see `features/tasks/pane/useDescriptionAutosave.ts` and its tests for the guarantees. Consecutive autosaves by the same person within 10 min fold into one activity entry.

- S1.4.2: an undo now marks the activity rows it records (the reversal) as undone too, matched by `request_id`, so feeds show neither the change nor its reversal. Seeded tasks have no history (the seed inserts rows directly), so their feeds start empty.

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
- [x] S1.1.1 Teams (+ undo registry, `POST /undo`, `GET /users`, PeoplePicker, InlineText, undo toasts) · [x] S1.1.2 Projects (+ favorites, sections table, fractional ordering, breadcrumbs) · [x] S1.1.3 Project members and roles (Share dialog, role matrix, last-admin guard)
- [x] S1.2.1 Sections (drag + menu reorder, collapse, undo; task move/delete hooks for S1.2.2) · [x] S1.2.2 Tasks (queued rapid entry, paste-to-batch, complete fade + Show completed, undo keeps position; section delete moves tasks) · [x] S1.2.3 Assignee and dates (AssigneePicker, DatePicker with NL input + calendar, DueText tones, A/M/D, `task.assigned`, assignee auto-follows) · [x] S1.2.4 DnD, multi-select, bulk (`POST /tasks/{id}/move`, `POST /tasks/bulk` all-or-nothing ≤500 → one undo batch; move undo detects later moves; section rebalancing; selection model; ↑↓/J/K, Shift, ⌘A, ⌘↑↓, ⌘Enter, ⌘⌫; multi-drag with drop line; bulk bar) · [x] S1.2.5 Filter/sort/group (API filters `assignee`=id|me|none, `due` buckets in the user's timezone, `sort`; `GET/PUT /me/prefs/views/{project}` atomic JSONB; URL params ⇄ prefs; client-side filtering for instant changes; edited rows stay visible until the view changes; drag off while sorted/grouped) · [x] S1.2.6 List performance (virtualized rows, lazy popovers, drop targets only while dragging, gzip; 2k tasks: 0.44 s render, 60 fps, 44 ms edits; see `docs/engineering/performance.md`)
- [x] S1.3.1 Pane (`?task=` pane + `/task/:id`; title, assignee, due/start, project; Tiptap description with Markdown paste; autosave with local drafts, hash-based conflicts, offline/sign-out safety, coalesced activity; J/K, Space, Esc; server-side rich-text sanitizing) · [x] S1.3.2 Subtasks (nested ≤5 levels; visibility through the top-level task, hidden with a deleted ancestor; reorder/outdent with undo; ↳ counts in one query; pane list; inline expansion; Tab / Shift+Tab on new rows) · [x] S1.3.3 Followers (follow/leave; editors add/remove collaborators, which grants task-only access; undo; `my_role` on task detail drives the pane)
- [x] S1.4.1 Comments (migration 0005: comments, mentions, reactions; sanitized rich text; @people/tasks/projects validated against what the author can see, mentioned people follow; author-only edit, author/admin delete, undo with conflict guard; fixed reaction set; device drafts for new comments and edits; JSON→React renderer instead of an editor per comment) · [x] S1.4.2 Activity feed (`GET /tasks/{id}/feed`: comments + task and subtask activity, oldest first, 300 max; undone changes and their reversals hidden, reorders hidden; readable sentences; All/Comments/Changes filter; runs of small edits folded) · [x] S1.4.3 Undo (coverage table test over 33 mutation types + handler registry check; session undo stack; ⌘Z outside text fields; shortcut sheet lists the real list shortcuts)
- [x] S1.5.1 My Tasks (migration 0006: per-user placements; synced lazily on read, so no background job: new assignments top of Recently assigned, reassigned/deleted drop out, tasks in a deleted project or under a deleted parent hide but keep their spot for restore; once-a-day pass in my timezone moves unpinned tasks by due date, hand-placed ones stay; drag and ⌘↑/⌘↓ between buckets with undo; completed view; concurrent first loads and first sign-ins race-safe) · [x] S1.5.2 Home (`GET /home` in one round trip: top 5 by due date then priority then My Tasks order; recent projects from my own activity on projects, sections, tasks and comments, visibility-checked, archived/deleted/templates excluded, topped up with starred then recently updated; overdue tasks I created or follow that others own; summary line; complete with undo from Home; pane opens in place; first-project prompt for new users)

### Phase 2: Daily-Use Parity
- [x] S2.1.1 WS hub and outbox dispatcher (`momentum/realtime/*`, migration 0007; see handoff notes above) · [x] S2.1.2 Realtime frontend client (`lib/realtime/*`; wired into ProjectTasksView, TaskPane/TaskPage, MyTasksPage, HomePage; see handoff notes below)
- [ ] S2.2.1 Board view · [ ] S2.2.2 Calendar view · [ ] S2.2.3 View switcher and defaults
- [ ] S2.3.1 Field definitions and library · [ ] S2.3.2 Fields in views · [ ] S2.3.3 Tags
- [ ] S2.4.1 Multi-homing · [ ] S2.4.2 Dependencies · [ ] S2.4.3 Milestones
- [ ] S2.5.1 Notification generation · [ ] S2.5.2 Inbox UI · [ ] S2.5.3 Notification preferences
- [ ] S2.6.1 Attachments · [ ] S2.6.2 Global search
- [ ] S2.7.1 Asana importer · [ ] S2.7.2 CSV import · [ ] S2.7.3 Onboarding

### Phases 3–9
Tracked in their phase files; copy the slice list here at each phase kickoff.

## Plan changes log
| Date | Change | Reason |
|---|---|---|
| 2026-09-23 | Backend tests use a real Postgres via `MOMENTUM_TEST_DATABASE_URL` + truncate-per-test, instead of testcontainers + SAVEPOINT | Build environment has no Docker; services commit normally, which keeps tests realistic |
| 2026-09-23 | Migrations live inside the package (`momentum/migrations`) | Hosts that install the package get migrations too (embedding) |
| 2026-09-23 | App wiring moved to `momentum/api/` (deps, runtime, system) | Keeps `core` free of outer-layer imports (import-linter) |
| 2026-09-23 | Queue names prefixed `momentum_`; NOTIFY channel `<schema>_events` | Coexist with a host that also uses Procrastinate/NOTIFY |
| 2026-09-23 | Base path handled by React Router `basename` (no custom link wrapper) | Simpler; tested |
| 2026-09-23 | S1.2.3: natural-language dates parse in the browser's timezone (not `users.timezone`) | The person typing sees their own clock; `users.timezone` is used server-side for derived dates and later for notifications/digests |
| 2026-09-23 | Added `docs/integrations/asana-import.md` and root `INTEGRATION_GUIDE.md` | Asana data migration spec; guide for plugging into another project |
| 2026-09-23 | Visual style changed to neutral + one blue accent, Inter only; tokens renamed to `canvas`/`sidebar`/`surface`/`surface-2`/`accent` (ADR-0005 amendment) | The inherited editorial style read as generic AI design; cheap to fix before Phase 1 |
| 2026-09-23 | Ordering jitter suffix 2 → 3 chars | 2 chars collided too often under concurrent inserts (flaky test) |
| 2026-09-23 | Final themes: Light = Paper (cream + ink accent), Dark = Graphite (charcoal + lime); palette picker removed (ADR-0005 amendment 2) | Blue/white rejected by the product owner; chosen from five options shown on the real UI |
| 2026-09-24 | Phase 2 started without a human sign-off gate on Phase 1, at explicit product-owner instruction ("finish off Phase 2 as you have all the context", "do not ask any permission... just finish this whole phase at ur own pace") given while unavailable | Phase 1 exit criteria were already met and the product owner asked to proceed rather than wait; noted here per that same instruction to record decisions/blockers instead of stopping |

## Phase retros
### Phase 1 (2026-09-23)
**Exit criteria:** all met. E2E J1, J3 and J2 (up to inbox delivery, which is Phase 2) pass with `make e2e`, plus a quick-add journey; the 2,000-task list renders in 0.44s and scrolls at 60fps (`docs/engineering/performance.md`); `tests/test_permission_matrix.py` covers 7 kinds of user x 9 task actions, and teams/projects/sections have their own matrices; `make check`: 158 backend and 124 web tests.

- **Went well:**
  - Checking every slice in a real browser against the production build caught what unit tests with mocks couldn't: rapid-create ordering, phantom autosaves, a double-follow insert on self-assigned quick adds, a quick-add project default race, and unreadable list rows on phones.
  - The generic undo registry with its coverage test kept "every mutation is undoable" true as features grew.
  - Syncing on read (My Tasks placements) avoided a background job and its failure modes.
- **Went less well:**
  - Mocked UI tests passed while the real app was wrong (single-project fixtures hid the default-project bug). New rule: fixtures should have at least two of whatever the code chooses between.
  - Two backend tests computed "today" in UTC instead of the user's timezone and failed late in the UTC day. Tests that depend on dates must use the actor's timezone.
  - The full parallel web suite needed more time for async queries (`asyncUtilTimeout` 4s). Flakes are fixed at the root, never retried away.
- **Watch in Phase 2:**
  - The initial JS bundle is 222 KB gzipped (Phase 0: 178 KB). Split Tiptap and dnd-kit out of the entry chunk before Board and Calendar add more.
  - Home and My Tasks resolve subtask ancestors one query per subtask. Fine at 10-15 users; batch it if profiles show it.
  - Realtime (Phase 2) should replace the refetch-on-focus and invalidate-on-close paths (Home, the pane).
- **Needs product-owner decision:** an assignee who isn't a project member can edit, move (between the project's sections) and delete that one task. All of these are undoable and documented in auth §6. Say if deleting should require project membership instead.

### Phase 0 (2026-09-23)
- Went well: portability tests from day one; the Easy Auth simulator exercises the real parser locally.
- Watch: bundle is 178 KB gz; keep the lazy-loading discipline in Phase 1 (editor, DnD).
- Lesson moved to docs: never `pkill -f` with a pattern that matches your own shell command (runbook troubleshooting).
