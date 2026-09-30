# STATUS

> Updated by the AI at the end of every slice and every session. The human confirms "done" after trying the slice.

> Older session handoff notes, the Phase 2 exit record and the Phase 0-1 retros live in `docs/progress/handoff-archive.md` (read them only when a slice touches that area). At the end of every slice, move the previous session's handoff there and keep only the latest one here.

## Current focus
- **Phase:** 6: Planning and Insight — **in progress** (see "Phase 6" under Progress). Phase 5: Agents v1 ("Teammates") — **complete and verified live** (exit criteria met 2026-09-29; four rounds of live verification closed 2026-09-30: live evals 219/220, every feature bucket above threshold, `RESULT: PASS`). Still deferred by agreement: the dogfood week (post-ship).
- **Next up:** Phase 6 slice by slice (Phase 6 section below).
- **Product-owner instruction (2026-09-26):** finish all remaining slices, then one big local test run against the real gateway (100+ questions/actions covering edge cases), then fix from that run.
- **Scope note (product owner, 2026-09-26):** the customer-operations capabilities (SQQ, pricing, contracts, invoices, pushes to internal systems as tools and assignable agents) will be done later in the product owner's own codebase, **not in this repo**. Finish the roadmap as written.
- **Branch:** Phases 3–4 are on `claude/clever-hopper-pbv7yr` (ahead of `main`). Phase 5 continues on `claude/intelligent-meitner-9ne4e8`, which starts from that branch's Phase 4 exit commit.
- **Standing instruction (product owner, 2026-09-26):** "push it all and finish the remaining slices": continue slice by slice through Phase 3, committing and pushing each.
- **Model:** Phase 5 is a whole-phase Opus 5.5 phase (`docs/process/model-guide.md` §2); the kickoff ran on Opus 5.5. (Phases 1 and 3 Opus; Phase 2 switched to Sonnet 5 mid-phase by product-owner instruction.)
- **Aliases (product owner, 2026-09-26):** keep the same Bedrock Sonnet 4 id for `fast`, `default` and `smart` for now. **Rerank:** approved for S3.1.4 as optional Cohere rerank, off by default.
- **AI mode:** everything through S3.5.1 was built and tested in **mock mode** (no LLM access in the build environment used then). The product owner's gateway is **Portkey**. **Real-gateway `llm-check` (product owner, 2026-09-26): 8/8 PASS, then 9/9 PASS after S3.1.2 added the catalog-schema row** — chat on all three aliases (all currently the same Bedrock Sonnet 4 id), tool calling (1.4 s), streaming, streaming with tool calls (so `LLM_SUPPORTS_STREAMING_TOOLS` stays `true`), embeddings for both input types at 1024 dims (vectors differ, so Portkey passes `input_type` through). A first run's streaming probe took 13 s in 2 chunks; a second run the same day took 1.5 s in 3 chunks, so that was a one-off. Coarse chunks (a few words each) are normal for Bedrock on a reply that short, and streaming works through Portkey.
- **Product owner's local machine (2026-09-26, S3.5.2):** native Windows dev machine (not a Linux container), with a real Portkey key already configured in `apps/api/.env` (`MOMENTUM_LLM_MODE=gateway`) — so the product owner's "one big local test run" can actually run from here (`EVALS_LIVE=1 make evals`), unlike earlier sessions.
- **Blockers:** none
- **Standing instruction (product owner, 2026-09-28):** finish all remaining Phase 5 slices one by one, committing and pushing each with a short report, without waiting for the live checkpoints; stop only for decisions that are the product owner's (CLAUDE.md §6) or if a live finding would change the design.
- **Phase 5 live checkpoints (agreed 2026-09-28):** the product owner pulls and runs the real gateway at 3 checkpoints, not every slice: **(1) after S5.1.2** (set `MOMENTUM_LLM_PRICE_TABLE`, `llm-check`, one manual agent run), **(2) after S5.2.1 + S5.3.8** (J10 by hand against the real model), **(3) phase exit** (`EVALS_LIVE=1 make evals`). Each slice report says whether a live check is needed; findings get fixed in the next slice.
- **Phase 5 AI mode:** mock mode throughout (no gateway in this environment). Deferred to the product owner's machine: `momentum llm-check`, `EVALS_LIVE=1 make evals` at phase exit. The dogfood exit criterion is a post-ship observation, not blocking.
- **Carried past Phase 4 exit** (kickoff Q6: the inbox/bell gap → S5.0.1 and the forms security review → S5.0.2 (**done**) are now Phase 5 slices; J1 flake **fixed** 2026-09-28, see handoff; the other two stay deferred): a security review pass of S4.2.1's public form endpoint (member-name exposure on assignee questions, no `X-Forwarded-For` handling); wiring `conversational_intake` into the `momentum/ai/evals/` harness (its `EvalWorld` has no notion of a form and the harness models one-shot input → output, not a stateless multi-turn feature); a real per-turn spam counter for conversational intake (currently reuses the submission rate limiter as a coarse guard); the inbox/bell live-update gap (**fixed in S5.0.1**) and the J1 quick-entry flake (**fixed**) found at exit (both described in the Phase 4 exit handoff, now in `handoff-archive.md`).

## Handoff notes (latest session: 2026-09-30, Phase 5 live verification closed)
- **Live verification round 4, closing (product owner, 2026-09-30):** `llm-check` 10/10, backend 738/738, frontend 334/334 (the clean re-run, all 67 files), live evals **219/220 (99.5%)**, all 21 feature buckets above threshold, **`RESULT: PASS`**. `agent_architect` went from 67% to 100%: the round-3 `stated_window` + `fit_dates` fix resolved all 4 consecutive failures. Full account: `docs/progress/phase-5-live-verification-findings.md` "Round 4".
  - **Open, not blocking:** `ai_step/draft_reply_answers_newest` gets 1/5 from the judge for a clean reply (a plain follow-up question, no invented facts), which the case's own rubric allows ("proposing an obvious next step… is not an invention"). A judge-consistency miss, not a product defect, and a different critique from the original "today is Monday" bug (clean 3 rounds running). Look at it next time the judge prompt is touched.
- **Live verification round 3 (product owner, 2026-09-30):** 217/220 (98.6%); plan_day 10/10. **Addressed (mock mode), awaiting the round 4 live run:**
  - Architect `brief_live` (4 failures in 4 runs, a real bug): the window a brief states is now enforced server-side: `stated_window` reads it in code, else the model's `window_days`, and `fit_dates` compresses the plan into it with a note (`project_brief/v2`).
  - ai_step `summarize_thread_content`: the summary kind now passes the task and thread to the judge as `source`, like the other two kinds.
  - `webinar_breakdown_proposed`'s empty reply, traced with a test: **not** the last-step fix. A tool call on the last step still ends in the model's answer or `OUT_OF_STEPS`, never an empty string, and Teammate has no `add_comment` to lose. The cause was older: the model wrote its answer beside its `create_subtasks` call and then ended with a blank turn, and the loop kept only the final turn's text. The loop now keeps the latest text written beside a tool call when the final turn is blank.
  - Still open: the frontend suite's clean re-run on your machine (killed by a memory guard, not a code issue), the round 4 live run, then close the Phase 5 retro.
- **Live verification round 2 (product owner, 2026-09-29):** 213/220 (96.8%); Pulse, Radar, Sorter and ai_step at 100%, the injection case passes; 4 buckets still under threshold. **Addressed (mock mode), awaiting the round 3 live run:**
  - plan_day: **decision: a blocked task never goes in Today**, even when due soon or urgent (it can't be started until its blocker is done; the rationale says what it waits on). `plan_day/v3` says so, the server enforces it, and the cases `mei_blocked_later` and `priya_blocked_urgent` now expect it (v2's "unless nothing else is urgent" was the loophole that let Mei's T-35 in).
  - Judge: `judge/v2` checks claims against the source material; agent_teammate cases now give it everything the model was shown, so `customer_email_draft`'s real $9/$29/$79 can be checked instead of guessed.
  - Stale cases: `pricing_decisions_summary` checks citations and content instead of `get_task`; `assigned_research` accepts `search_tasks` or `semantic_search` (new `agent_tools_any` check).
  - chat's `grounded` check: an answer that says it found nothing isn't grounded, whatever it cites for context (eval scorer only; the product's own `grounded` flag, which drives "No sources from your workspace cited", is unchanged).
  - `agent_architect/brief_live`: untouched; re-run it 3 times live first (`momentum evals --live --feature agent_architect --case brief_live`, three times).
  - **Still open:** the round 3 live run (`momentum llm-check`, `momentum evals --live --report-dir ../../reports/evals`), then close the Phase 5 retro below with the final numbers.
- **Live verification (product owner, 2026-09-29):** `llm-check` 10/10, backend 726/726, web 334/334, J10 e2e passes; live evals 211/221 (95.5%) with 5 of 21 feature buckets under threshold. Full findings: `docs/progress/phase-5-live-verification-findings.md`. **Fixed the same day, in mock mode, awaiting the live re-run:**
  - Pulse and Radar asked for bare `T-12` citations; only `[T-12]` counts. Their prompts now ask for brackets and moved to versioned files (`pulse_intro/v1`, `radar_note/v1`).
  - `ai_step_reply/v2`: never states or assumes today's date or day (the model isn't told it), nor what happened after the newest comment. Re-run `ai_step/draft_reply_answers_newest` 3 times before calling it fixed (Phase 3 retro precedent).
  - Sorter charter: makes a lead's call from the title (typo → low), says when Risk is High/Medium, asks for the exact duplicate format, and works in three turns within its 8 steps.
  - Teammate charter: doesn't re-fetch the task it's shown, batches lookups, proposes subtasks only when explicitly asked, and proposes nothing when the request tries to direct it (decision below).
  - The tool loop's last allowed step now asks the model to answer with what it has, so runs stop ending in "I couldn't finish that" (the cause of both live `max_steps` failures).
  - `plan_day/v2`: the capacity is a ceiling, not a target (Ana's webinar, due in 10 days with no priority, stays out of Today); a blocked task is explained in words.
  - `agent_draft/server_corrects_the_draft` is now mock-only (`live: false`, a new case flag): it checks the server's corrections of a scripted bad draft; the live model's draft needed none, so there were no notes to show.
  - Found while verifying: after 18:30 UTC (midnight in Asia/Kolkata) a Pulse test and the Radar mock eval failed, because the test's actor had UTC but the user row Asia/Kolkata, and the Radar/Nudge eval triggers used UTC while the eval data's dates are relative to the project owner's day. Test and eval fixes only; the product code was right.
  - **To do on your machine:** `momentum agents install --force --only triage --only teammate` (their definitions changed), then `momentum llm-check` and `EVALS_LIVE=1 make evals`, and record the outcome in the Phase 5 retro.
- **Phase 5 is complete** (exit criteria met; see `phase-5.md` "Phase 5 exit"). This session shipped S5.2.1–S5.2.3, S5.0.2, and all eight starter agents; per-slice notes are in `handoff-archive.md`.
- **What's there now, in short:**
  - Assign or @mention an agent on a task: it answers in the thread (@mentioning you) and hands the task back for review.
  - Agent gallery, create an agent from a description, edit, test run, Run now, and "Works in" (give an agent access to projects you manage) on each agent's page.
  - Starters: Teammate and Sorter are model-driven tool loops; Pulse, Herald, Nudge, Radar, Architect and Scribe are built-in code-backed agents (code selects and limits, the model only writes prose or plans).
  - Security review of public forms (S5.0.2), with a deploy action: `MOMENTUM_TRUSTED_PROXY_HOPS=1` on Azure App Service.
- **Found and fixed along the way (worth knowing):** custom-field changes had no activity or undo since Phase 2; an agent planning a project couldn't see its asker's teams; the prefs loader mangled booleans; a new trigger option would have marked every installed agent as edited; the pickers and feed didn't know agent accounts.
- **Your checklist on the real gateway (deferred by agreement):**
  1. `make migrate` (0030 is new), then `momentum agents install --force` (or `--only <key>` for agents you haven't edited: the definitions of all eight changed this session).
  2. Set `MOMENTUM_LLM_PRICE_TABLE` (agent budgets count dollars once the model is priced; until then the 2M-token cap).
  3. `momentum llm-check`, then `EVALS_LIVE=1 make evals` (nine new agent eval features; live-only cases are the real test of their prompts).
  4. J10 by hand (checkpoint 2): switch Teammate on, give it a project in "Works in", assign it a task.
  5. Dogfood week: switch on Pulse, Herald and Sorter, add them to projects; acceptance is on each agent's page.
- **For the next session (read this first):**
  - **Branch:** `claude/intelligent-meitner-9ne4e8`, everything pushed.
  - **Fresh cloud container:** `apt-get install -y postgresql-16-pgvector`; `initdb` into `/home/user/.pgdata` as `postgres`; start with `pg_ctl -o '-p 5432 -k /tmp'`; create role `momentum`/`momentum` (createdb) and databases `momentum` + `momentum_test`; create the `vector`, `pg_trgm` and `citext` extensions in `template1`; then `make install`. Postgres **stops when the container sleeps**: `pg_isready -h 127.0.0.1` before trusting a wall of DB errors. `make check` takes about 11 minutes, so run it in the background; run `ruff format` and `prettier --write` first (a format miss costs a full rerun). E2E: `pnpm build`, then `MOMENTUM_E2E_CHROMIUM=/opt/pw-browsers/chromium pnpm exec playwright test` in `apps/web` (J10 takes ~2 minutes of worker ticks).
  - **Next:** the Phase 6 kickoff (read `docs/roadmap/phase-6.md`; the model guide says which model), after the product owner's live run above. Radar's forecast signals and Architect's capacity hook are the Phase 6 extension points.

## Open questions
| # | Question | Needed by | Status |
|---|---|---|---|
| 1 | Model ids for the `fast` and `smart` aliases (gateway = Portkey; `default` = the Bedrock Sonnet id from the product owner's pipeline; Cohere = English embed v3, 1024 dims) | Before `EVALS_LIVE` runs (Phase 3 exit) | **answered 2026-09-26:** the same Sonnet 4 id for all three aliases for now; revisit with usage data |
| 2 | Office Azure constraints (region, networking, Entra app registration owner) | Phase 9 kickoff (ask during Phase 7) | open |
| 3 | Target host project for plugging in (stack/auth) | Before Phase 8 | open (INTEGRATION_GUIDE.md covers all modes) |
| 4 | Add an optional Cohere rerank step (rerank-v3.5 via the gateway) to S3.1.4 hybrid retrieval, off by default? (kickoff Q2) | S3.1.4 | **answered 2026-09-26: yes**, off by default |
| 6 | Phase 5 kickoff Q1–Q7 (agent access, autonomy defaults, rollout, budgets, Pulse default time, carry-overs, Nudge snooze) | S5.1.1 | **answered 2026-09-28:** all recommendations accepted (see `phase-5-kickoff.md` §5) |
| 7 | When a person asks an agent (assign/@mention/run now), may it use access that person lacks? | S5.1.3 | **answered 2026-09-29:** no, only what both see (lower role); scheduled/event runs keep the agent's own access |
| 5 | MCP server dropped. Keep personal API tokens (so internal scripts can call Momentum's API), or drop S7.1 entirely? | Phase 7 | **answered 2026-09-28: keep**, moved to Phase 5 as S5.1.6 (ADR-0009) |

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
- [x] S4.1.1 Rule model and executor (2026-09-27) · [x] S4.1.2 Actions library (2026-09-27) · [x] S4.1.3 Rule builder UI and run history (2026-09-27) · [x] S4.1.4 NL → rule (2026-09-27) · [x] S4.1.5 AI step action (2026-09-27)
- [x] S4.2.1 Form builder (+ public forms) (2026-09-27) · [x] S4.2.2 Conversational intake (2026-09-28) · [x] S4.3.1 Project templates (2026-09-28) · [x] S4.3.2 Task templates (2026-09-28) · [x] S4.3.3 Template from description (2026-09-28) · [x] S4.4.1 Approvals (2026-09-28) · [x] S4.4.2 Recurring tasks (2026-09-28) · [x] Phase 4 exit (2026-09-28)

### Phase 5: Agents v1 ("Teammates")
- [x] Kickoff (`docs/roadmap/phase-5-kickoff.md`, 2026-09-28)
- [x] S5.0.1 Inbox and bell live updates (2026-09-28) · [x] S5.0.2 Public forms security review (2026-09-29)
- [x] S5.1.1 Agent model and accounts (2026-09-28) · [x] S5.1.2 Runtime loop and triggers (2026-09-28) · [x] S5.1.3 Runs UI (2026-09-29) · [x] S5.1.4 Autonomy, budgets, kill switches (2026-09-29) · [x] S5.1.5 Extension points and code-backed agents (2026-09-29) · [x] S5.1.6 API tokens (2026-09-29)
- [x] S5.2.1 Assign a task to an agent (2026-09-29) · [x] S5.2.2 @mention an agent (2026-09-29) · [x] S5.2.3 Agent gallery + create from description (2026-09-29)
- [x] S5.3.1 Pulse (2026-09-29) · [x] S5.3.2 Sorter (2026-09-29) · [x] S5.3.3 Herald (2026-09-29) · [x] S5.3.4 Nudge (2026-09-29) · [x] S5.3.5 Architect (2026-09-29) · [x] S5.3.6 Scribe (2026-09-29) · [x] S5.3.7 Radar (2026-09-29) · [x] S5.3.8 Teammate (2026-09-29)
- Build order (kickoff Q3, Q8): S5.0.1 before S5.1.3 · E5.1 (incl. S5.1.5, S5.1.6) → S5.2.1 + S5.3.8 (J10) → S5.2.2 → S5.2.3 → Pulse, Sorter (after S5.0.2), Herald, Nudge, Radar → Architect, Scribe
- [x] Phase 5 exit (2026-09-29): J10 passes (e2e, mock); budget-cap test; runs page explains every action
- [x] Phase 5 live verification (2026-09-30, four rounds): `llm-check` 10/10, live evals 219/220 (99.5%), all 21 buckets pass · deferred: dogfood week (post-ship)

### Phases 6–9
Tracked in their phase files; copy the slice list here at each phase kickoff.

### Phase 6: Planning and Insight
> Started 2026-09-30 in parallel with Phase 5's live close-out, at the product owner's instruction, on its own branch `claude/inspiring-bohr-p9xomo` (cut from `claude/intelligent-meitner-9ne4e8` at `8c7de80`). This section is Phase 6's own; the Phase 5 sections above belong to the other session until the branches are merged.

- **Model:** kickoff on Opus 5.5; per-slice tags from `model-guide.md` §4 (S6.1.1 is Opus).
- **Baseline:** `make check` green on `8c7de80` (backend 738/738, web 334/334, lint, format, types, import contracts). A fresh container needs Postgres (the Phase 5 handoff recipe) **and** `pnpm install` in `apps/web` (no root `package.json`); without the latter, `types-check` fails with error 254.
- **Kickoff answers (product owner, 2026-09-30):** every recommendation accepted (Q1 custom SVG timeline, Q2 split S6.1.1, Q3 capacity, Q4 backtest, Q5 visibility, Q6 J11/J12), plus a UX bar: "the WOW factor, easy for the user to view data, better than Asana" (in `phase-6.md`).
- **Standing instruction (product owner, 2026-09-30):** do what's recommended and continue slice by slice, committing and pushing each.
- **Next up:** S6.4.2 AI rebalancing (a greedy heuristic proposes reassignments and date moves from the workload model; the model writes only the explanation; PreviewCard; one-undo batch).
- **Noticed, not fixed (outside Phase 6 slices):** (1) LLM output in mock mode isn't marked with the purple *mock* indicator anywhere in the UI (CLAUDE.md data-honesty rule; a gap since Phase 3, needs a small app-wide slice); (2) autogenerate reports constraint-name drift on `agents`/`agent_runs` unique constraints (Phase 5 names vs. the naming convention); harmless, but review any autogenerated migration before keeping it.
- **Live check for the product owner (not blocking):** new live-only eval cases, run with the next `EVALS_LIVE=1 make evals`: `command/push_blocker_and_its_dependents`, `command/reschedule_keeps_dependents_in_order` (Mo's `reschedule_task`, S6.1.2) `nl_rule/unblocked_move_to_build` (S6.1.3), and the new `goal_check_in` feature's `launch_goal_live` and `metric_on_pace_live` (S6.3.2). Prompt versions bumped: `nl_rule/v5`, `template_from_brief/v2`. Run `make migrate` (0031–0034 are new).
- **S6.1.1a notes:** the timeline is live on every project's Timeline tab; try it on **Load Test Timeline (500)** (`momentum seed --perf`). Its synthetic data has many conflicts and overdue tasks by design (random dates), so expect a lot of crit. `tools/perf/timeline-perf.mjs` measures it and takes screenshots.
- [x] Kickoff (`docs/roadmap/phase-6-kickoff.md`, 2026-09-30); answers recorded, refinements applied to `phase-6.md`
- [x] S6.1.1a Timeline rendering (2026-09-30) · [x] S6.1.1b Timeline editing (2026-09-30) · [x] S6.1.2 Dependency-aware rescheduling (2026-09-30) · [x] S6.1.3 Dependency hand-offs (2026-09-30; added 2026-09-30: templates keep dependencies, "you're up" notification, `task.unblocked` rule trigger)
- [x] S6.2.1 Project overview tab (2026-09-30) · [x] S6.2.2 Portfolios (lite) (2026-09-30)
- [x] S6.3.1 Goals (2026-09-30) · [x] S6.3.2 AI for goals (2026-09-30)
- [x] S6.4.1 Workload view (2026-09-30; estimates editable end to end, `capacity` overrides, `/workload`, Architect on the capacity model) · [ ] S6.4.2 AI rebalancing
- [ ] S6.5.1 Dashboards · [ ] S6.5.2 Ask for a chart · [ ] S6.5.3 Forecasting and risk score
- [ ] Phase 6 exit

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
| 2026-09-28 | Phase 5 kickoff: new E5.0 (S5.0.1 inbox/bell live updates, S5.0.2 public forms security review) carried from Phase 4; kickoff refinements on S5.1.1/S5.1.2/S5.1.4 and the starter table (token-fallback budget, `agent_alert` kind, workspace timezone, explicit `croniter`, Sorter enabled via scope, Nudge snooze on `my_task_placements`); build order changed to put S5.3.8 with S5.2.1 (J10) | Product-owner answers to kickoff Q1–Q7; state check in `phase-5-kickoff.md` §2 |
| 2026-09-28 | ADR-0009: agent extension points. Host tools and agent definitions, code-backed `handler` agents, `get_attachment_text` (new S5.1.5); API tokens moved from S7.1 to S5.1.6 | Product owner's customer-operations work (SQQ, discovery, invoices, contracts, data uploads) will live in their own codebase and plug into Momentum; kickoff Q8. Onboarding-specific workflow features (conditional template items, template versions applied to running projects, agent form pre-fill, document generation) are deliberately not on the roadmap; the product owner will do them later |
| 2026-09-29 | Six of the eight starter agents are built-in code-backed agents (Pulse, Herald, Nudge, Radar, Architect, Scribe), not model tool loops; schedules gained `at: digest_time` and `per: project`, event filters `top_level`; a handler's proposals are previewed as the person they're for | Coverage, limits and "never invent" hold by construction when code selects and the model only writes; a plain schedule has no person to propose to, so per-project fan-out; previews as the applier match "applied with the applier's permissions" (S5.1.2) without widening agent access |
| 2026-09-30 | Project from brief (and Architect): a window the brief states ("over the next four weeks") is enforced as the plan's end date (parsed in code, else the model's `window_days`), with the existing compression and note; the tool loop answers with text written beside a tool call when the final turn is blank | Four live runs out of four planned past an explicit four-week window; the prompt alone can't be trusted with a hard constraint (same lesson as plan_day). An agent's answer was lost when the model put it in the same turn as its tool call |
| 2026-09-29 | Plan My Day: a blocked task never goes in Today, even when due soon or urgent (prompt v3 plus a server rule); the round-2 alternative, "include it with a caveat in case the blocker clears", was rejected | It can't be started until its blocker is done, so it would crowd out work that can; when the blocker completes it's unblocked and the next plan picks it up. Matches the existing cases and `priya_blocked_urgent`'s rubric |
| 2026-09-29 | Eval quality (round 2): the judge sees the source material (judge v2, agent_teammate passes what the model was shown); `pricing_decisions_summary` and `assigned_research` expectations updated to the intended behaviour; chat's "grounded" check excludes answers that say they found nothing | Each was a harness fault shown by the round-2 report, not a model fault; each change is stated in its case file |
| 2026-09-29 | Live-eval fix: an agent request that tries to direct it ("ignore your instructions", reassign everything) gets **no proposals at all**, plus a line saying the instruction was ignored; the eval bar `proposes_nothing` stays. Decided by the AI, the product owner to confirm | The live run proposed unrelated subtasks alongside an injection; Teammate's charter already limited subtasks to explicit asks, and quietly doing other work after an injection is surprising. Stricter than needed is the safe side; loosening the case would hide the next regression |
| 2026-09-29 | The tool loop's last allowed step carries a one-off "answer now" note (tools still attached, calls on it not run); eval cases can be `live: false` | Two live cases ended in `OUT_OF_STEPS` with their work half-reported; a case that checks our code against a scripted bad model output has nothing to check live |
| 2026-09-29 | Requested agent runs see only what both the agent and the requester can see (`ctx.acting_for` honoured in `domain/access.py`, lower role of the two) | Product-owner answer to a permissions question raised while building S5.1.3 (kickoff Q9) |
| 2026-09-24 | Phase 2 started without a human sign-off gate on Phase 1, at explicit product-owner instruction ("finish off Phase 2 as you have all the context", "do not ask any permission... just finish this whole phase at ur own pace") given while unavailable | Phase 1 exit criteria were already met and the product owner asked to proceed rather than wait; noted here per that same instruction to record decisions/blockers instead of stopping |
| 2026-09-30 | S6.4.1: a week's capacity override is set in hours ("Away all week" = 0), not PTO days; Architect keeps the open-task count as a fallback for unestimated work | Hours cover part days and short weeks with one control; without the fallback a team that doesn't estimate would never get a capacity warning |

## Phase retros
### Phase 5 (2026-09-29, live verification closed 2026-09-30)
**Exit criteria: met** (J10 e2e against the real worker; the $0.01 budget test; a trace step for every action). **Verified end to end against the real gateway** in four live rounds: `llm-check` 10/10, backend 738/738, frontend 334/334, live evals **219/220 (99.5%), all 21 feature buckets above threshold, `RESULT: PASS`**. Deferred by agreement: the dogfood week (post-ship). Full account in `docs/roadmap/phase-5.md` "Phase 5 exit" and `docs/progress/phase-5-live-verification-findings.md`.

**Live verification, round by round:**

| Round | Live evals | Found and fixed |
|---|---|---|
| 1 | 211/221 (95.5%), 5 buckets under threshold | Pulse/Radar citation format (`[T-12]`), Sorter's field-setting and duplicate format, Teammate proposing on an injection, ai_step assuming today's date, plan_day treating capacity as a target, runs ending in `OUT_OF_STEPS` |
| 2 | 213/220 (96.8%), 4 under | plan_day's decision, not just its wording (a blocked task never goes in Today, enforced server-side); the judge now sees the source material; three stale cases corrected |
| 3 | 217/220 (98.6%), 2 under | Architect planned past a brief's stated window (4/4 runs): the window is now enforced in code (`stated_window` + `fit_dates`); ai_step's summary kind passes its source to the judge; an answer written beside a tool call is no longer lost |
| 4 | **219/220 (99.5%), 0 under — PASS** | Clean. One judge-consistency case left (below) |

- **Went well (live verification):**
  - Every round found something real, and every fix went into the product, not the thresholds: no case was loosened to pass, and the one case made mock-only (`server_corrects_the_draft`) checks our code against a scripted bad model, which has nothing to check live.
  - Enforcing a hard constraint in code beat prompting for it, twice: plan_day's "blocked never in Today" and Architect's date window both flapped under prompt-only fixes and went to 100% once the server enforced them. **Rule:** when a live case fails the same constraint twice, move the constraint into code.
  - Reading each failing output before calling it anything kept the numbers honest: several round-1/2 "failures" were harness faults (a judge without its source, stale expectations), and round 4's one miss is a judge contradicting its own rubric, not a product defect.
- **Went less well:**
  - The judge needed the source material to judge grounding at all (`judge/v2`); it should have had it from the start. **Rule:** a judge always gets what the model was shown.
  - A frontend run on the product owner's machine was killed by a memory guard and briefly read as a failure; re-run before reporting.
- **Open, not blocking:** `ai_step/draft_reply_answers_newest`: the judge scores a clean follow-up question 1/5 against its own rubric. Revisit when the judge prompt is next touched.

- **Went well:**
  - Code-backed agents turned out to be the right default for most starters. When code gathers, counts and applies limits and the model only writes the prose, the evals' hardest criteria (coverage, no invented tasks, rate limits, no nudges on blocked work) hold by construction, and a quiet day costs nothing. ADR-0009's handler mechanism, built for the product owner's scripts, carried six of the eight starters.
  - Reusing the S3 features (status draft, project from brief, break down) inside agents with a `propose_action=False` switch kept one implementation per feature.
  - Every new optional schema field (`at`, `per`, `top_level`) is omitted when unset, so installed agents' hashes didn't change; a test pins that.
- **Went less well:**
  - Two long-standing gaps surfaced only because an agent needed them: custom-field changes never recorded activity or undo (since Phase 2), and there was no UI to give an agent a project (found only when writing J10). **Rule:** when a slice depends on "undo works" or "an admin can set this up", check it through the UI or the activity table, not just the service.
  - A snapshot of serialized config (hashes) is fragile: adding one optional field would have marked every installed agent as edited. **Rule:** new optional fields on stored config are excluded when unset, with a test.
  - Formatting misses cost two full `make check` reruns (~11 minutes each). **Rule:** format before starting the gate.
- **Watch in Phase 6:**
  - The live-only agent eval cases have never met the real model; expect the first `EVALS_LIVE=1` run to find prompt issues (Phase 3's lesson), and fix them before tuning thresholds.
  - Agent budgets are in tokens until the price table is set.
  - Architect's capacity count and Radar's heuristics are placeholders for Phase 6's capacity and forecast models: replace them, don't stack on them.

### Phase 4 (2026-09-28)
**Exit criteria: met.** J9 passes against the real embedded worker; rule loop protection proven (`test_rules.py`); live evals — nl_rule 20/20 (100%), every feature above threshold; a new integration test proves form → triage → assignment end to end through the real executor. Full account in `docs/roadmap/phase-4.md` "Phase 4 exit".

- **Went well:**
  - Schema foresight paid off directly: `tasks.type`/`approval_state`, the notification `kind` check constraint, and `recurrence`'s base shape were all designed in during Phase 1/2, so S4.4.1 needed no migration at all and S4.4.2 needed exactly one column. Worth doing again when a later phase's shape is knowable in advance.
  - The "draft in names, resolve to ids server-side, ask back on anything unresolved" pattern (S4.1.4's `nl_rule`) reused cleanly for S4.3.3's AI templates, and needed *less* infrastructure than the original because a project template's payload already stores role placeholders instead of real people — no name-resolution step at all.
  - Running the full e2e suite at exit (not just the one new journey) caught two real things a slice-scoped run never would have: the inbox/bell live-update gap, and confirmation that a pre-existing flake (J1) predates this phase rather than being introduced by it.
- **Went less well:**
  - A vocabulary-parity test (`test_the_model_vocabulary_matches_the_rule_schemas_and_the_prompt`) meant two slices that were "just" a domain-schema change (S4.4.1's `approval.decided` trigger, S4.4.2's monthly recurrence fields) also required touching `nl_rule.py` and bumping its prompt version, in the same slice, even though neither was otherwise about AI. **Rule:** when `domain/rules/schemas.py`'s trigger/action vocabulary changes, check `ai/nl_rule.py` in the same slice, not as an afterthought.
  - J9 needed three attempts to get right: the first two board-drag failures turned out to be about *drag timing on a freshly-created card* and *the inbox having no live subscription*, not the rules engine (which worked correctly from the first direct-API check). **Rule:** when a UI journey fails, isolate the backend with a direct API call before assuming the feature itself is broken — it narrowed the search from "is the rule system broken" to "is this specific page's data fresh" in minutes instead of more UI-only guessing.
  - The inbox/bell gap went unnoticed through S2.5.1, S2.5.2 and three more Phase 4 slices that create notifications, because nothing before J9 exercised "does a notification appear on a page you're already looking at" — only "does it exist after a fresh load."
- **Needs a follow-up slice (not blocking this exit):**
  1. Live-subscribe the inbox page and the topbar bell to `user:<id>`, the way Home/My Tasks already do (S2.5.1's `notification.created` event already carries everything needed).
  2. Investigate the `j1-core-flow.e2e.ts` quick-entry flake on this machine (S1.2.2's rapid keyboard entry dropped a task twice in a row; unrelated to Phase 4, but reproducible here).
  3. The carried-forward items from the "Current focus" deferred list above (forms security review, conversational-intake eval coverage, per-turn spam counter).

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
