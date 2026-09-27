# STATUS

> Updated by the AI at the end of every slice and every session. The human confirms "done" after trying the slice.

> Older session handoff notes, the Phase 2 exit record and the Phase 0-1 retros live in `docs/progress/handoff-archive.md` (read them only when a slice touches that area). At the end of every slice, move the previous session's handoff there and keep only the latest one here.

## Current focus
- **Phase:** 3: AI Layer v1 ("Mo") — **complete; exit criteria met** (2026-09-27; see the Phase 3 retro and `docs/roadmap/phase-3.md` "Phase 3 exit"). Awaiting the product owner's sign-off. Kickoff done (`docs/roadmap/phase-3-kickoff.md`); S3.1.1–S3.5.2 done. Phase 2 is complete.
- **Next up:** **Phase 4, S4.1.5 AI step action (Sonnet)** (S4.1.1-S4.1.4 done 2026-09-27). Phase 3 is done (product-owner sign-off given by starting Phase 4). Each slice is a fresh session that follows `docs/process/slice-session.md` and ends by printing the next slice's prompt. The one open product-owner item (set `MOMENTUM_LLM_PRICE_TABLE`) does not block.
- **Product-owner instruction (2026-09-26):** finish all remaining slices, then one big local test run against the real gateway (100+ questions/actions covering edge cases), then fix from that run.
- **Scope note (product owner, 2026-09-26):** the customer-operations capabilities (SQQ, pricing, contracts, invoices, pushes to internal systems as tools and assignable agents) will be done later in the product owner's own codebase, **not in this repo**. Finish the roadmap as written.
- **Branch:** all Phase 3 work is on `claude/clever-hopper-pbv7yr` (ahead of `main`). Continue from that branch.
- **Standing instruction (product owner, 2026-09-26):** "push it all and finish the remaining slices": continue slice by slice through Phase 3, committing and pushing each.
- **Model:** Phase 3 is a whole-phase Opus 5.5 phase (`docs/process/model-guide.md` §2); S3.1.1–S3.1.5 were built on Opus 5.5. (Phase 1 Opus; Phase 2 switched to Sonnet 5 mid-phase by product-owner instruction.)
- **Aliases (product owner, 2026-09-26):** keep the same Bedrock Sonnet 4 id for `fast`, `default` and `smart` for now. **Rerank:** approved for S3.1.4 as optional Cohere rerank, off by default.
- **AI mode:** everything through S3.5.1 was built and tested in **mock mode** (no LLM access in the build environment used then). The product owner's gateway is **Portkey**. **Real-gateway `llm-check` (product owner, 2026-09-26): 8/8 PASS, then 9/9 PASS after S3.1.2 added the catalog-schema row** — chat on all three aliases (all currently the same Bedrock Sonnet 4 id), tool calling (1.4 s), streaming, streaming with tool calls (so `LLM_SUPPORTS_STREAMING_TOOLS` stays `true`), embeddings for both input types at 1024 dims (vectors differ, so Portkey passes `input_type` through). A first run's streaming probe took 13 s in 2 chunks; a second run the same day took 1.5 s in 3 chunks, so that was a one-off. Coarse chunks (a few words each) are normal for Bedrock on a reply that short, and streaming works through Portkey.
- **This session's environment (2026-09-26, S3.5.2):** native Windows dev machine (not a Linux container), with a real Portkey key already configured in `apps/api/.env` (`MOMENTUM_LLM_MODE=gateway`) — so the product owner's "one big local test run" can actually run from here (`EVALS_LIVE=1 make evals`), unlike earlier sessions.
- **Blockers:** none

## Handoff notes (latest session: 2026-09-27, S4.1.4 NL → rule)
- **Shipped:** `POST /ai/rules/compile` (`momentum/ai/nl_rule.py`, `prompts/nl_rule/v1.md`, `default` alias, temperature 0): a sentence → either a validated rule draft (exactly the body `POST /rules` takes, `created_from_prompt` included) plus a readable sentence, or a question — never both. The model answers in **names** and the server resolves them to ids inside the rule's own project (reference block: the project's sections, people, tags, attached custom fields, and up to 40 other visible projects by name); unknown or ambiguous names, phrases the engine can't express (Slack, AI steps, "due within 3 days") and drafts that fail `RuleIn` validation all come back as a question instead of a guess. Frontend: a "Describe a rule" box in `RulesDialog` → the draft opens in the ordinary `RuleBuilder` (new `draft` prop) with an amber "Mo drafted this" header, editable, saved through the normal create call; hidden while AI is off. Evals: new feature `nl_rule` with the AC's 20 phrases + `rule_exact` scorer; the eval workspace now seeds tags (`tags:` in `launch_v1.yaml`). New `service.authorize_manage` reuses `create_rule`'s admin check before any model call. Details in `docs/roadmap/phase-4.md` S4.1.4 "Built".
- **Decisions:** (1) the model works in names, the server resolves ids — a model shouldn't copy uuids, and resolution then enforces the same project scope `_check_references` does; (2) compile is **project-scoped only** (workspace rules stay API-only, as in S4.1.3) and needs project **admin**, checked before the model call; (3) if the model returns both a complete rule and a question, the rule wins (the question would block a usable draft; the prompt asks for one or the other); (4) the draft's `TriggerType`/`ActionType`/`Op` literals are a deliberate second copy of the rule vocabulary (they become enums in the `submit_result` schema, which is what makes exact JSON reliable) — a test fails if they or the prompt drift from `domain/rules/schemas.py`, including if either ever offers `slack_message`/`ai_step`; (5) the server returns its own readable sentence (the builder still renders its own from `ruleMeta.ts`) so the API answer is complete on its own.
- **Live evals (final run):** `nl_rule` **20/20 (100%)**, threshold 90%: 18 phrases compiled to exactly the expected JSON, 2 asked back (Slack; a section that doesn't exist). 45.6k tokens, p50 2.4 s. An earlier run was 18/20 and found a real gap — the reference block listed no other projects, so `add_to_project`/`remove_from_project` could never resolve; both misses were that. Mock suite still 1.0.
- **Mutation checks (3, all killed):** compile permission lowered to editor (endpoint permission test failed); `_pick` returning the first hit on an ambiguous name (ask-back test failed); the model's question ignored when it drafted no rule (Slack refusal test failed). Frontend: dropping `created_from_prompt` from the builder's save (the draft test failed).
- **Verification:** backend **518/518** green (ruff, mypy strict, import-linter, pytest 19:52); web prettier/tsc/eslint green and vitest **294/295** — the one failure is `projects.test.tsx`'s "creates a project in a team" (untouched by this slice) hitting the 15 s **test timeout** under full-suite load; it passes on its own and passed in an earlier full run the same day, and the whole web suite now takes ~24 min with jsdom built 56 times. **This machine's web suite is load-flaky, not red:** every file this slice touched passed. Worth acting on next session (vitest `pool: 'vmThreads'`, or a higher `testTimeout`) rather than re-rolling the dice. Live evals as above. No migration, no new setting, no new AI tool (compile creates nothing, so it needs no risk level).
- **Gotchas:** `RulesDialog.test.tsx` is slow (8 full-app renders, ~40-120 s) and flaked once on a render timeout, passing on re-run — worth splitting, and see the suite-wide timing note above. The eval workspace's `tags:` are created through `create_tag`, so a workspace that already has a tag of that name is left alone. A compiled rule's name is the model's wording (trimmed, ≤200 chars) with the typed sentence as a fallback.
- **Deferred:** the AI step action (S4.1.5), Slack (P7), NL → rule for **workspace** rules (no UI for those at all yet), compiling an *edit* to an existing rule ("also notify Mei"), and custom-field references are untested live (the eval workspace has no custom fields; the unit tests cover the unknown-field ask-back).

## Open questions
| # | Question | Needed by | Status |
|---|---|---|---|
| 1 | Model ids for the `fast` and `smart` aliases (gateway = Portkey; `default` = the Bedrock Sonnet id from the product owner's pipeline; Cohere = English embed v3, 1024 dims) | Before `EVALS_LIVE` runs (Phase 3 exit) | **answered 2026-09-26:** the same Sonnet 4 id for all three aliases for now; revisit with usage data |
| 2 | Office Azure constraints (region, networking, Entra app registration owner) | Phase 9 kickoff (ask during Phase 7) | open |
| 3 | Target host project for plugging in (stack/auth) | Before Phase 8 | open (INTEGRATION_GUIDE.md covers all modes) |
| 4 | Add an optional Cohere rerank step (rerank-v3.5 via the gateway) to S3.1.4 hybrid retrieval, off by default? (kickoff Q2) | S3.1.4 | **answered 2026-09-26: yes**, off by default |
| 5 | MCP server dropped. Keep personal API tokens (so internal scripts can call Momentum's API), or drop S7.1 entirely? | Phase 7 | open |

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
- [x] S2.2.1 Board view · [x] S2.2.2 Calendar view · [x] S2.2.3 View switcher and defaults
- [x] S2.3.1 Field definitions and library · [x] S2.3.2 Fields in views (reduced scope: no filter/sort/group by field yet) · [x] S2.3.3 Tags
- [x] S2.4.1 Multi-homing · [x] S2.4.2 Dependencies · [x] S2.4.3 Milestones
- [x] S2.5.1 Notification generation · [x] S2.5.2 Inbox UI · [x] S2.5.3 Notification preferences
- [x] S2.6.1 Attachments · [x] S2.6.2 Global search
- [x] S2.7.1 Asana importer (reduced scope) · [x] S2.7.2 CSV import · [x] S2.7.3 Onboarding
- [x] Phase 2 exit: J2 (extended to inbox delivery)/J4/J5/J6 pass as real Playwright E2E journeys (`apps/web/e2e/`, alongside J1/J3 from Phase 1), retro, STATUS — **Phase 2 complete**

### Phase 3: AI Layer v1 ("Mo")
- [x] Kickoff (`docs/roadmap/phase-3-kickoff.md`)
- [x] S3.1.1 LLM gateway + `llm-check` · [x] S3.1.2 Tool registry + sweep (17 tools; `semantic_search` → S3.1.4, `create_status_update` → S3.4.3) · [x] S3.1.3 AI actions (preview → apply → undo) · [x] S3.1.4 Embeddings + hybrid retrieval (+ optional rerank, off) · [x] S3.1.5 Workspace memory + context builders
- [x] S3.2.1 Smart quick-add (24 local + 6 AI fixture phrases) · [x] S3.2.2 ⌘K natural-language commands (J7 passes)
- [x] S3.3.1 Ask Mo chat backend + panel (J8 passes) · [x] S3.3.2 Contextual entry points
- [x] S3.4.1 Summaries · [x] S3.4.2 Break into subtasks · [x] S3.4.3 Draft status update · [x] S3.4.4 Writing help · [x] S3.4.5 Plan my day · [x] S3.4.6 Project from brief
- [x] S3.5.1 Eval harness (141 cases since the Phase 3 exit; mock 23/23) · [x] S3.5.2 AI usage and settings (admin)
- [x] Phase 3 exit (2026-09-27): `EVALS_LIVE=1 make evals` against the real gateway **passes: 141/141, every threshold** (one clean full pass on the final code) · e2e 9/9 incl. J7, J8 (mock) · backend, web, lint, types green · AI-unavailable degrades gracefully · usage token counts exact; **dollar cost unmeasured until a price table is set**

### Phase 4: Workflow and Intake
- [x] S4.1.1 Rule model and executor (2026-09-27) · [x] S4.1.2 Actions library (2026-09-27) · [x] S4.1.3 Rule builder UI and run history (2026-09-27) · [x] S4.1.4 NL → rule (2026-09-27) · [ ] S4.1.5 AI step action
- [ ] S4.2.1 Form builder (+ public forms) · [ ] S4.2.2 Conversational intake · [ ] S4.3.1 Project templates · [ ] S4.3.2 Task templates · [ ] S4.3.3 Template from description · [ ] S4.4.1 Approvals · [ ] S4.4.2 Recurring tasks · [ ] Phase 4 exit

### Phases 5–9
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
| 2026-09-26 | Gateway treated as "any OpenAI-compatible gateway", not LiteLLM specifically: added `MOMENTUM_LLM_API_KEY_HEADER` + `MOMENTUM_LLM_EXTRA_HEADERS` (ADR-0004 amendment) | The product owner uses Portkey, which takes its key in its own header |
| 2026-09-26 | `llm_calls` gains `prompt_version`; `agent_run_id` without FK until Phase 5; rows written in their own transaction | ai-architecture §7 records prompt versions there; usage of rolled-back requests must still count |
| 2026-09-26 | Production startup requires `MOMENTUM_LLM_MODE=gateway` while AI is enabled | Never a silent mock fallback in production (CLAUDE.md §3) |
| 2026-09-26 | S3.1.2: AI tools live in `momentum/ai/tools/`, not per-domain `tools.py` files (coding-standards §2 example updated) | The domain layer never imports AI; tools call services like any other caller |
| 2026-09-26 | S3.1.2: `semantic_search` registered in S3.1.4 and `create_status_update` in S3.4.3 instead of S3.1.2's "all Phase 1–2 tools" sweep | Their backing tables (`embeddings`, `status_updates`) arrive in those slices |
| 2026-09-26 | Phase 7: MCP server dropped (S7.1) | Product owner: not required |
| 2026-09-26 | Aliases: `fast`/`default`/`smart` all point at the same Sonnet 4 id for now; S3.1.4 gets optional Cohere rerank, off by default | Product-owner answers to kickoff Q1/Q2 |
| 2026-09-26 | Phase 3 exit: eval scorer takes the asker's text (echoing it is not a leak); `clarifies` accepts a question in words; the judge sees proposed operations; three cases corrected | The first live run's failures were mostly harness/case faults, found by reading each failure (see phase-3.md "Phase 3 exit") |
| 2026-09-26 | Phase 3 exit: `search_tasks.blocked`, `blocked_by` in task briefs, `from`/`to` for moved dates in project activity | Real gaps: Mo could not answer "which tasks are blocked" or "did anything slip" from list results |
| 2026-09-24 | Phase 2 started without a human sign-off gate on Phase 1, at explicit product-owner instruction ("finish off Phase 2 as you have all the context", "do not ask any permission... just finish this whole phase at ur own pace") given while unavailable | Phase 1 exit criteria were already met and the product owner asked to proceed rather than wait; noted here per that same instruction to record decisions/blockers instead of stopping |

## Phase retros
### Phase 3 (2026-09-27)
**Exit criteria: met.** Live evals pass (141/141, one clean full pass on the final code, after eight earlier runs that each found something); J7, J8 pass in a real browser; AI-off degrades gracefully; token counts exact. **Open:** dollar cost is unmeasured (no price table).

- **Went well:**
  - The eval harness paid for itself on the first live run: it found real gaps mock mode could never show (no way to list blocked tasks, no old-to-new dates in project activity, prompts that under-reported or invented), including a real privacy gap (`get_task` naming blockers in private projects), found only because a mutation check on a related change made me look.
  - Reading every failure instead of chasing the pass rate: roughly half of the "failures" were the harness or the case being wrong (a judge given no text, no source material, a rubric asking for what the feature can't see). Fixing those first made the number mean something.
  - Making the harness honest, not lenient: outages are reported as INCOMPLETE, partial runs can't become a baseline, regressions compare like with like, and no threshold was lowered.
  - The gateway was fine: ~2-5 s per call and no rate-limit or streaming problems across ~1.4 M tokens per run.
- **Went less well:**
  - The harness was never run against a live model before the exit, so its own bugs surfaced only then. **Rule:** a new eval feature needs one live case before it is called done.
  - I called a repeat failure "judge noise" before checking; it was a real prompt weakness. **Rule:** a case that fails twice is a finding, not noise.
  - Scripted doc/code edits (string replaces) silently missed or wrote the wrong line endings several times on Windows; the Edit tool and an assert on every replace are the rule (already noted at S3.1.5, and it recurred).
  - E2E had not been run on this machine, so J1 had been broken since S3.4.6 unnoticed, and the e2e server was quietly using the real gateway. **Rule:** run `e2e` at least once at each phase exit on the machine you will keep working on.
  - Docker Desktop stopped mid-session and took the shell and a run with it; I first misread the symptom as a code problem.
- **Watch in Phase 4:**
  - Live results vary run to run: expect the odd single-case miss; run a flapping feature 3x before tuning (the inbox summary was checked that way: 3/3, 30/30 cases).
  - Chat spends ~19 k tokens per question (~700 k per 35 cases). Fine now; check before agents (Phase 5) multiply it.
  - `fast`/`default`/`smart` are still the same model, so alias-specific behavior (e.g. fast summaries) is untested.
  - Prompts were edited in place and are still `v1`, so recorded `prompt_version` doesn't distinguish the old wording: bump the version on the next prompt change.
- **Needs product-owner decision:**
  1. **Set `MOMENTUM_LLM_PRICE_TABLE`** for the Bedrock Sonnet 4 id and the embed model. Until then cost shows as "not measured" (the admin page and `llm-check` now say so) and `MOMENTUM_AI_MONTHLY_BUDGET_USD` can't be enforced. Or say if the budget should count tokens instead (I did not change budget semantics: it touches AI autonomy defaults).
