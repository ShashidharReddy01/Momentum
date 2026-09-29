# STATUS

> Updated by the AI at the end of every slice and every session. The human confirms "done" after trying the slice.

> Older session handoff notes, the Phase 2 exit record and the Phase 0-1 retros live in `docs/progress/handoff-archive.md` (read them only when a slice touches that area). At the end of every slice, move the previous session's handoff there and keep only the latest one here.

## Current focus
- **Phase:** 5: Agents v1 ("Teammates") — in progress: kickoff done (2026-09-28, `docs/roadmap/phase-5-kickoff.md`), E5.1 (S5.1.1–S5.1.6), S5.0.1, E5.2 (S5.2.1–S5.2.3) and S5.3.8 done. Phase 4 complete (exit criteria met 2026-09-28).
- **Next up:** Phase 5 exit (J10 e2e, retro, INTEGRATION_GUIDE log).
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

## Handoff notes (latest session: 2026-09-29, S5.2.1 + S5.3.8 Assign a task to an agent + Teammate)
- **Shipped:** you can assign a task to an agent.
  - The assignee picker offers enabled agents that act when assigned (amber ✦ ring, "✦ Agent"); agent assignees show with the ring everywhere; the toast says it will reply in the comments.
  - Within a minute the agent answers in the thread, @mentioning you. A long answer (over 4,000 characters) is attached as a Markdown file, with its opening in the comment.
  - Then it hands the task back: to a "Review"/"In review" section if the project has one, else back to the task's creator. Undoable; skipped if someone reassigned the task meanwhile.
  - **Added (small, flagged):** when a run you asked for fails or is stopped, you get a notification that opens the run and says why. Before, an assigned task could sit waiting in silence.
  - Teammate (S5.3.8): a real charter; `add_comment` removed from its tools (its answer is posted anyway), `get_attachment_text` added. Base agent prompt v2: on assigned work the answer is the work itself.
  - Eval feature `agent_teammate`: 10 cases (3 mock, 7 live-only with rubric judging), live threshold 85%.
  - Full account in `docs/ai/agents.md` §3 "As built" and `phase-5.md` S5.2.1.
- **Verification:** `make check` green: backend **692** (685 + 7 in `tests/test_agent_assign.py`), web **323**, API types regenerated; mock evals `agent_teammate` 3/3 (all 10 run without errors under `--all`).
- **Live check: checkpoint 2 is now possible** on your machine (J10 by hand):
  1. `make migrate` (no new migration in this slice), `momentum agents install --only teammate --force` (the definition changed)
  2. enable Teammate, give it editor access to a project
  3. assign it a task with a request in the description; `make dev` runs the worker
  4. within a minute: a reply that @mentions you, and the task goes back to you (or to a "Review" section)
  5. optionally `EVALS_LIVE=1 make evals` with `--feature agent_teammate`
- **S5.2.2 done (2026-09-29):** @mentioning an agent. The composer's @ list offers only people and the agents that answer mentions (✦ Agent); a mention added by editing a comment counts too (once per comment); the reply @mentions you. Verification: `make check` green, backend **695** (+3 in `tests/test_agent_mention.py`), web **323**.
- **S5.2.3 done (2026-09-29):** an Agents page in the sidebar (gallery), "Create agent" with "✦ Describe what you want" (Mo drafts it; anything it got wrong is fixed and listed before you save), an Edit page, and a **Test run** on each agent's page that shows what it would say and change without changing anything (works while it's switched off). Verification: `make check` green, backend **697** (+2 in `tests/test_agent_gallery.py`), web **326** (+3); mock evals `agent_draft` 1/1.
- **S5.0.2 done (2026-09-29):** public forms security review, 3 findings fixed (details in `phase-5.md` S5.0.2):
  - Public forms no longer show assignee questions: they listed every project member's name to anyone with the link.
  - Nobody can assign a form's task to someone the form doesn't offer (anonymous: never; signed in: the project's people).
  - The per-IP rate limit could be dodged with a fake `X-Forwarded-For`. **Action for deployment:** set `MOMENTUM_TRUSTED_PROXY_HOPS=1` on Azure App Service (default 0 = no proxy).
  - Verification: `make check` green, backend **701** (+4 in `tests/test_forms_security.py`), web **326**.
- **S5.3.1 Pulse done (2026-09-29):** the weekday digest.
  - Arrives in the inbox at each person's own digest time (08:30 by default), on their behalf.
  - Lists what's due today, overdue, and unread assignments, mentions and updates since the last digest; the model only adds one "start here" line, which is dropped if it mentions anything not on the lists.
  - No digest (and no AI cost) when there's nothing to report or someone turns "Daily digest (Pulse)" off in notification settings.
  - Also fixed on the way: adding the per-person time to schedules would have marked every installed scheduled agent as "edited"; now it's invisible when unused.
  - **Deploy note:** run `momentum agents install --only daily_digest` (Pulse is now a built-in code agent).
  - Verification: `make check` green, backend **708** (+7 in `tests/test_agent_pulse.py`), web **326**; mock evals `agent_pulse` 3/3.
- **S5.3.2 Sorter done (2026-09-29):** triage of new tasks.
  - When a task is created in a project Sorter has been added to, it proposes a priority, a field such as Risk, and a "possible duplicate" comment, as one proposal to the person who created the task. Subtasks are skipped.
  - New AI tool `set_field_value`; the AI now sees a task's custom fields.
  - **Found and fixed:** custom-field changes (by people, rules, templates or AI) were never recorded in the activity log and couldn't be undone. They now are, and show in the task's feed as "changed Risk".
  - Deploy: `momentum agents install --only triage`.
  - Verification: `make check` green, backend **712** (+4 in `tests/test_agent_sorter.py`; the tool snapshot and catalog test updated for the new tool), web **328**; mock evals `agent_sorter` 3/3.
- **S5.3.3 Herald done (2026-09-29):** weekly project status drafts.
  - Fridays at 15:00 (workspace time), for each project Herald has been added to, it drafts a status update from the week's real activity and sends it to the project's owner to publish. A quiet week gets no draft and costs nothing.
  - "@Herald" on a task drafts one on the spot, for whoever asked, with a reply in the thread.
  - Deploy: `momentum agents install --only status_reporter`.
  - Verification: `make check` green, backend **716** (+4 in `tests/test_agent_herald.py`), web **328**; mock evals `agent_herald` 1/1.
- **S5.3.4 Nudge done (2026-09-29):** friendly reminders on overdue and stalled tasks.
  - Weekdays at 10:00, in projects Nudge has been added to: one short comment to the assignee on tasks overdue by more than a day or untouched for 5 days, at most every 2 days; the 4th reminder also asks the project owner to check in, then it stops.
  - Never nudges done tasks or tasks waiting on someone else's work. You can snooze it per task ("Snooze Nudge reminders" in the task menu) or turn it off in notification settings.
  - Migration 0030. Deploy: `make migrate`, then `momentum agents install --only nudger`.
  - Verification: `make check` green, backend **720** (+4 in `tests/test_agent_nudge.py`), web **329** (+1); mock evals `agent_nudge` 1/1.
- **S5.3.7 Radar done (2026-09-29):** project risk notes.
  - Each weekday morning, for projects Radar has been added to: overdue share, tasks waiting on overdue or blocked work, unassigned tasks due within 3 days, and fast scope growth.
  - The result shows as an amber note on the project's Overview (with a link to how it decided), and as a "Project risks" line in the owner's Pulse digest. It changes nothing itself.
  - Deploy: `momentum agents install --only risk_watcher`.
  - Verification: `make check` green, backend **722** (+2 in `tests/test_agent_radar.py`), web **331** (+2); mock evals `agent_radar` 2/2.
- **S5.3.5 Architect done (2026-09-29):** planning on request.
  - Give Architect a brief ("Run now" on its page, paste or load a text file, pick a project) and it proposes a whole project plan to you; assign or @mention it on a task and it proposes subtasks. You review and apply.
  - It notes when a suggested owner already has a lot due in the plan's window (full capacity planning is Phase 6).
  - New "Run now" panel on agent pages (Architect, Scribe, and any agent you can run by hand).
  - Deploy: `momentum agents install --only planner`.
  - Verification: `make check` green, backend **724** (+2 in `tests/test_agent_architect.py`), web **333** (+2); mock evals `agent_architect` 2/2.
- **S5.3.6 Scribe done (2026-09-29):** meeting notes to tasks.
  - Paste or load notes (or a VTT transcript) in Scribe's "Run now", or run it on a task with the notes attached (Word, PDF and text files work): it lists the decisions and proposes one task per action item, with the owner and date when the notes give them, linked back to the notes.
  - **All eight starter agents are built.**
  - Deploy: `momentum agents install --only meeting_notes`.
  - Verification: `make check` green, backend **726** (+2 in `tests/test_agent_scribe.py`), web **333**; mock evals `agent_scribe` 1/1.
- **For the next session (read this first):**
  - **Branch:** `claude/intelligent-meitner-9ne4e8`, everything pushed.
  - **Fresh cloud container:** `apt-get install -y postgresql-16-pgvector`; `initdb` into `/home/user/.pgdata` as `postgres`; start with `pg_ctl -o '-p 5432 -k /tmp'`; create role `momentum`/`momentum` (createdb) and databases `momentum` + `momentum_test`; create the `vector`, `pg_trgm` and `citext` extensions in `template1`; then `make install`. Postgres **stops when the container sleeps**: `pg_isready -h 127.0.0.1` before trusting a wall of DB errors. `make check` takes about 10 minutes, so run it in the background.
  - **Decisions already made, don't re-ask:** kickoff Q1–Q9 (`phase-5-kickoff.md` §5).
  - **Mock mode throughout.**
  - **Remaining:** the phase exit (J10 e2e in the browser, retro, INTEGRATION_GUIDE log).
- **Next up:** Phase 5 exit (J10 e2e, retro, INTEGRATION_GUIDE log).

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
- [ ] Phase 5 exit: J10 (mock); budget-cap test; runs page explains every action · deferred: `llm-check` + `EVALS_LIVE=1 make evals` (product owner's machine), dogfood week (post-ship)

### Phases 6–9
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
| 2026-09-28 | Phase 5 kickoff: new E5.0 (S5.0.1 inbox/bell live updates, S5.0.2 public forms security review) carried from Phase 4; kickoff refinements on S5.1.1/S5.1.2/S5.1.4 and the starter table (token-fallback budget, `agent_alert` kind, workspace timezone, explicit `croniter`, Sorter enabled via scope, Nudge snooze on `my_task_placements`); build order changed to put S5.3.8 with S5.2.1 (J10) | Product-owner answers to kickoff Q1–Q7; state check in `phase-5-kickoff.md` §2 |
| 2026-09-28 | ADR-0009: agent extension points. Host tools and agent definitions, code-backed `handler` agents, `get_attachment_text` (new S5.1.5); API tokens moved from S7.1 to S5.1.6 | Product owner's customer-operations work (SQQ, discovery, invoices, contracts, data uploads) will live in their own codebase and plug into Momentum; kickoff Q8. Onboarding-specific workflow features (conditional template items, template versions applied to running projects, agent form pre-fill, document generation) are deliberately not on the roadmap; the product owner will do them later |
| 2026-09-29 | Requested agent runs see only what both the agent and the requester can see (`ctx.acting_for` honoured in `domain/access.py`, lower role of the two) | Product-owner answer to a permissions question raised while building S5.1.3 (kickoff Q9) |
| 2026-09-24 | Phase 2 started without a human sign-off gate on Phase 1, at explicit product-owner instruction ("finish off Phase 2 as you have all the context", "do not ask any permission... just finish this whole phase at ur own pace") given while unavailable | Phase 1 exit criteria were already met and the product owner asked to proceed rather than wait; noted here per that same instruction to record decisions/blockers instead of stopping |

## Phase retros
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
