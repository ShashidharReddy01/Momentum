# Phase 6 Kickoff

**Date:** 2026-09-30 · **Model:** Opus 5.5 for the kickoff (`docs/process/model-guide.md` §2); Phase 6 is not a whole-phase Opus phase, so the per-slice tags in §4 of the guide apply (S6.1.1, S6.1.2, S6.4.2, S6.5.2, S6.5.3 are Opus) · **Phase goal:** see and plan across time, people and goals: timeline, overview, portfolios, goals, workload, dashboards and forecasts.

**Status:** kickoff written, **awaiting the product owner's answers to §4** (Q1 blocks S6.1.1). The refinements in §2 are proposals; they go into `phase-6.md` once §4 is answered, as at the Phase 5 kickoff.

**Parallel start:** started on 2026-09-30 at the product owner's instruction while Phase 5's live verification is still closing out in another session on `claude/intelligent-meitner-9ne4e8`. This work lives on its own branch (`claude/inspiring-bohr-p9xomo`, cut from that branch at `8c7de80`) and doesn't touch the Phase 5 sections of `STATUS.md`. The two branches get merged once both are done.

## 0. Prerequisite: mock mode and the gateway

As in Phases 3 and 5, this environment has no LLM gateway, so the AI slices (S6.3.2, S6.4.2 explanations, S6.5.2, S6.5.3's risk explanation) are **built and tested in mock mode**. Live checks go to the product owner's machine: the 15 "ask for a chart" fixture questions (an exit criterion) need one `EVALS_LIVE=1` run. Most of Phase 6 isn't AI at all: timeline, workload, dashboards and the forecast itself are deterministic code.

## 1. State check

Baseline: `claude/intelligent-meitner-9ne4e8` at `8c7de80` (Phase 5 live round 3). `make check` **green**: backend 738/738, web 334/334, lint, format, types, import contracts.

### Code reality vs. what `phase-6.md` assumes

| Area | What Phase 6 assumes | Reality after Phase 5 | Consequence |
|---|---|---|---|
| Timeline tab | A project view | `ProjectPage.tsx` already lists `timeline` as a view tab gated to phase 6; `projects.default_view` already allows `timeline`, `overview`, `dashboard`; `frontend-architecture.md` reserves `features/timeline/` and says timeline and charts load lazily | S6.1.1 fills the tab in; no migration for the view key |
| Task dates | Bars start → due | `tasks.start_on`/`due_on` exist and are on `TaskOut`; `update_task` rejects `dates_out_of_order`. Calendar (S2.2.2) already draws multi-day bars and drags/resizes them with dnd-kit through `useTaskMutations` | Reuse the Calendar's date mutation and realtime wiring; the timeline is a new renderer, not a new write path |
| Milestones | Diamonds | `tasks.type='milestone'` (S2.4.3) | Nothing to add |
| Dependencies | Arrows for a whole project | Only **per task**: `GET /tasks/{id}/dependencies`. There is no project-wide list, and `TaskOut` carries no blocker info | **New endpoint** `GET /projects/{id}/dependencies` (edges between the project's visible tasks) in S6.1.1; 500 per-task calls would miss the "smooth at 500 tasks" bar |
| Batch undo | S6.1.2's cascade as one batch | `POST /tasks/bulk` (≤500, one undo batch) and batch undo exist (S1.2.4, S1.4.3) | S6.1.2 builds the cascade on the same batch mechanism |
| Overview | Brief editor, members, milestones, status history, dates, status draft, Radar note | The Overview tab shows **status updates, ✦ Draft status update and Radar's `RiskNote`** (S3.4.3, S5.3.7). `projects.brief`, `brief_text`, `start_on`, `due_on` **exist in the table since 0003 but no schema, service or UI reads or writes them** | S6.2.1 exposes project dates and brief through the projects service (activity + undo). The forecast's "vs due" feature (S6.5.3) needs `projects.due_on` to be settable, so S6.2.1 comes before S6.5.3 |
| Status updates for portfolios/goals | Check-ins as status updates | `status_updates.entity_type` already allows `project`, `portfolio`, `goal` (0020). `favorites.entity_type` is free text and data-model.md already lists `portfolio`, `goal`, `dashboard` | S6.2.2 / S6.3.1 reuse `status_updates`; no new check-in table |
| Planning tables | `portfolios`, `portfolio_items`, `goals`, `goal_links`, `capacity`, `dashboards`, `dashboard_widgets`, `forecasts` | **None exist.** Sketched in data-model.md §8 (no `workspace_id` on `capacity`, `forecasts`, `portfolio_items`, `goal_links`, `dashboard_widgets`) | Every new table gets `workspace_id` (CLAUDE.md §3, embeddable) and lives in the configured schema. data-model.md §8 is updated per slice |
| Effort | Workload sums `estimate_minutes` | The column exists since 0004 but **nothing exposes it**: not on `TaskOut`/`TaskPatchIn`, no pane field, no import mapping. Every task has `NULL` | Workload would always fall back to task counts. S6.4.1 must add estimates to the API, the pane and CSV import first (§2) |
| Capacity | "From settings (30h/week)" (phase-6.md) vs. "default from user prefs" (data-model.md) | Neither exists. `users.timezone` is set per user (seed users span 11 timezones) | The two docs disagree → Q3 |
| Architect's capacity hook | Phase 6 replaces it | `agents/architect.py` `capacity_notes()` warns at `CAPACITY_WARN = 8` open tasks due in the plan window (a placeholder) | S6.4.1 swaps the count for the capacity model (Phase 5 retro: "replace them, don't stack on them") |
| Radar's signals | Forecast joins Radar | `agents/radar.py` `signals()` computes **overdue ratio, blocked chains, unassigned near-due, scope growth**: four of the five risk-score features S6.5.3 lists | S6.5.3 reuses `signals()` as its feature extractor and adds "forecast vs due"; Radar then reads the stored score instead of recomputing. One definition of each signal |
| Plan My Day's `CAPACITY = 8` | – | Tasks per day in Today, a different concept from weekly hours | Left alone; noted so nobody "unifies" them by accident |
| Charts | Recharts with tokens | Not installed. `frontend-architecture.md` already names Recharts for Phase 6 dashboards and bespoke SVG for small visuals | S6.5.1 adds `recharts` (lazy chunk), justified in the slice report |
| Reporting queries | `query_metrics` tool, safe query builder | Nothing exists (`ai/usage_report.py` is AI usage only). The tool catalog lists `query_metrics` (read, Phase 6) | S6.5.1 builds the query-spec executor in the domain layer; S6.5.2 registers the tool over it |
| Forecast history | Backtest "on seed history" | The seed (`momentum/seed.py`) has **no history to backtest**: completions only in the last 6 days, no `start_on`, no estimates, no dependencies, ~a dozen tasks per project | The exit criterion can't be met on today's seed → a deterministic synthetic history generator (§2, Q4) |
| Monte Carlo | 10k runs per project nightly | No numerical library in the backend (`numpy` isn't installed) | Q4: pure Python with a small run count per task vs. adding `numpy` |
| Phase 6 journeys | "Phase-6 journeys" (roadmap) | `testing-strategy.md` §4 stops at J10; no Phase 6 journey is defined | Q6 proposes J11 and J12 |
| Perf harness | 500 timeline tasks "smoothly" | `momentum seed --perf` adds a 2,000-task list project (no dates, no dependencies); `tools/perf/list-perf.mjs` measures the list | S6.1.1 adds a dated, dependency-linked perf project and a timeline measurement, with a budget in `performance.md` |

### Lessons from earlier retros that apply here
- **Phase 5:** "Architect's capacity count and Radar's heuristics are placeholders for Phase 6's capacity and forecast models: replace them, don't stack on them." Built into the S6.4.1 and S6.5.3 refinements.
- **Phase 5:** check "undo works" and "an admin can set this up" through the UI or the activity table, not only the service. Applies to every new entity (portfolios, goals, dashboards, capacity overrides).
- **Phase 5:** new optional fields on stored config are omitted when unset, with a test (dashboard `query_spec` and widget `viz` JSON will be versioned the same way).
- **Phase 5:** format before starting the gate (`ruff format`, `prettier --write`); `make check` takes ~11 minutes.
- **Phase 4:** when a UI journey fails, isolate the backend with a direct API call first (J11's drag and cascade).
- **Phase 3:** a new eval feature needs one live case before it's called done; a case that fails twice is a finding, not noise (S6.5.2's 15 fixtures).
- **Phase 1 (S1.2.6):** measure performance in a production build, not the dev server, with the numbers written to `performance.md`.

## 2. Proposed refinements (applied to `phase-6.md` once §4 is answered)

| Slice | Change | Reason |
|---|---|---|
| S6.1.1 | **Split** into **S6.1.1a Timeline rendering** (rows grouped by section, bars, 1-day bars for due-only tasks, unscheduled tray, milestone diamonds, dependency arrows, today line, week/month/quarter zoom, row virtualization, `GET /projects/{id}/dependencies`, perf project + measurement) and **S6.1.1b Timeline editing** (drag to move, resize edges, `←/→` nudge, drag from the tray to schedule, realtime, undo toasts) | An L slice that will pass the ~600-line guard (ai-dev-workflow §3); the 500-task bar is a rendering question and should be measured before interactions are layered on (Q2) |
| S6.1.1 | Top-level tasks only; subtasks are not rows (a count on the bar); "Show completed" as in the list | Matches ux-specs §4.5 ("rows = tasks grouped by section"); subtasks would multiply the row count past the perf budget |
| S6.1.1 | Timeline perf budget: 500 tasks with ~300 dependencies render < 1 s after data arrives, pan/scroll at 60 fps, drag feedback < 50 ms (production build, same method as S1.2.6) | Makes "smoothly" measurable |
| S6.1.2 | The cascade is computed in the **tasks service** (`plan_reschedule` → dry-run preview of every shifted dependent, then one `bulk` batch, one undo), shown with the `PreviewCard` diff pattern; the "keep dependents fixed" option applies only the moved task and returns the conflicts (dependent starts before its blocker's due) for the crit highlight | One write path; the same planner can later back an AI tool without a second implementation |
| S6.2.1 | Adds project `start_on`, `due_on` and brief (`brief` JSON + `brief_text`) to the projects schemas and service (activity + undo), plus the overview layout; keeps the existing status history, draft button and `RiskNote` | The columns exist but nothing writes them; the forecast needs `due_on` |
| S6.2.2 | `portfolios`, `portfolio_items` with `workspace_id`; project rows filtered by what the viewer can see (Q5) | Embeddable rule; permissions |
| S6.3.1 | `goals`, `goal_links` with `workspace_id`; check-ins are `status_updates(entity_type='goal')` | The check constraint already allows it |
| S6.4.1 | **Estimates first:** `estimate_minutes` on `TaskOut`/`TaskPatchIn` (activity + undo), an Effort field in the pane (`3h`, `90m`), a CSV import mapping, and `update_task`'s tool gains it | Without it the effort mode is always empty |
| S6.4.1 | Capacity per Q3; `capacity` rows are **weekly overrides only** (PTO, part-time weeks), keyed `(workspace_id, user_id, week_start)`; weeks start Monday in the person's own timezone | Resolves the doc conflict; no row per person per week for the common case |
| S6.4.1 | Architect's `capacity_notes()` switches to the capacity model (planned effort in the window vs. capacity) and `CAPACITY_WARN` goes away | Phase 5 retro |
| S6.4.2 | A greedy heuristic in Python first (no ILP solver dependency); the AI writes only the explanation; proposals go through the existing preview → apply → undo | Keep dependencies deliberate; "code decides, the model writes prose" worked for six of Phase 5's eight agents |
| S6.5.1 | `recharts` added as a lazy chunk; `query_spec` v1 validated by a Pydantic model (entity ∈ tasks; filters from `search_tasks`' vocabulary; `group_by` ∈ assignee, section, project, status, priority, custom field, tag; `measure` ∈ count, sum(estimate); `time_bucket` ∈ day, week, month) and executed through the same visibility clause as other bulk reads, **as the viewer** | Safe by construction; no raw SQL; a shared dashboard never shows more than its viewer may see |
| S6.5.2 | `query_metrics` (read) wraps the same executor; the 15 fixture questions become an eval feature (`ai/evals/cases/chart/`) with mock fixtures and at least one live-only case | Phase 3 rule: one live case before "done" |
| S6.5.3 | Reuse Radar's `signals()` for the risk features, add "forecast vs due"; Radar reads the stored `forecasts` row (score + drivers) instead of recomputing; the forecast marker appears on the timeline and overview | One definition per signal; Phase 5 retro |
| S6.5.3 | **Deterministic synthetic history** (`momentum seed --history`, fixed RNG seed): ~20 finished projects over ~6 months with dated completions, estimates and dependencies. The backtest replays each project from its midpoint and reports the share that finished on or before their P80 date; **pass = 70–90%** (P80 ± 10 points). Script: `momentum forecast-backtest` | The current seed can't be backtested; "within ±10%" needs a stated metric |
| New settings | `MOMENTUM_WORKLOAD_DEFAULT_HOURS` (30), `MOMENTUM_FORECAST_RUNS` (Monte Carlo runs, 10000), `MOMENTUM_FORECASTS_ENABLED` (nightly job kill switch) | Environment facts come from settings (CLAUDE.md §3); documented in `configuration.md` + `.env.example` in their slices |
| Build order | S6.1.1a → S6.1.1b → S6.1.2 → S6.2.1 → S6.2.2 → S6.3.1 → S6.3.2 → S6.4.1 → S6.4.2 → S6.5.1 → S6.5.2 → S6.5.3 | As listed in the phase file, with S6.2.1 before S6.5.3 (project `due_on`) and S6.4.1 before S6.4.2 (capacity) |

## 3. Risks and unknowns

| Risk | Mitigation / spike |
|---|---|
| Timeline performance at 500 tasks with arrows (SVG node count, arrow re-routing during drag) | Row virtualization with fixed row height (as the list); arrows drawn only for visible rows and their off-screen endpoints clipped; the dragged bar's arrows recomputed alone; measured in S6.1.1a before S6.1.1b |
| A Gantt library's own state store fighting React Query and realtime (if Q1 = SVAR) | Custom SVG avoids it; with SVAR, treat it as a controlled view and route every edit through our API |
| Forecast calibration on synthetic data proves little about the real team | State it in the retro; keep the backtest script so it can run on real history after go-live (Phase 9 imports real data) |
| Monte Carlo cost (10k runs × tasks × active projects, nightly) | Measured per project; `MOMENTUM_FORECAST_RUNS` caps it; runs on the maintenance queue |
| Dashboards leaking data through aggregates (a count over a private project) | Every query runs as the viewer with the visibility clause; tests with a private project in the fixture |
| NL → query spec producing valid but wrong charts | Spec validation + preview before "Add to dashboard"; 15 fixture questions scored on the spec, not the prose |
| Workload overload shown from invisible work, or hidden by it | Q3 decides what the grid counts |
| Merging with the Phase 5 branch later | Phase 6 doesn't edit the Phase 5 sections of `STATUS.md` or Phase 5's eval case files; migrations are numbered after 0030 (if Phase 5's close-out adds a migration, renumber at merge time) |

## 4. Questions for the human

- **Q1 (S6.1.1): SVAR React Gantt or a custom SVG timeline?**

  | | SVAR React Gantt 2.7.3 | Custom SVG |
  |---|---|---|
  | Licence | Core **MIT**. Critical path, auto-scheduling, baselines, work calendars, export and vertical markers are in the **paid PRO edition** | Ours |
  | Size (measured here: esbuild, minified, React external) | **~244 KB min / ~83 KB gzip JS**, plus up to ~22 KB gzip CSS across its packages; 16 `@svar-ui/*` packages + `date-fns` 3 | Estimated ~800–1,200 lines of TS, no new dependency; reuses `@tanstack/react-virtual` and `@dnd-kit` (already installed) |
  | Styling with our tokens | Its own theme (Willow) driven by ~300 `--wx-*` CSS variables; mappable to our tokens, but its toolbar, grid, editor and menus bring their own look, and upgrades can add unmapped variables | Complete: bars, diamonds, arrows and the today line use `var(--proj-n)`, `--crit`, `--ok`, `--amber` directly; the ESLint "no raw colours" rule applies as everywhere |
  | Fit with our data flow | Keeps its own store (`gantt-store`) with its own undo and link editing; we'd have to disable those and mirror React Query + realtime into it | Reads `useProjectTasks` + the new dependencies endpoint; edits go through `useTaskMutations`, so undo toasts, realtime and conflict handling work as in the list, board and calendar |
  | What we'd use from it | Rendering, zoom scales, drag/resize | – |
  | What we'd build anyway | Cascade preview (S6.1.2, server-side), forecast marker and conflict highlighting (the free marker API is PRO), the unscheduled tray | The same, plus the rendering |

  **Recommendation: custom SVG.** Its free tier leaves out the parts we'd use most (critical path, markers), its store duplicates ours, and 80–100 KB gzip plus a second design language is a lot to take on for bars and arrows we can draw in ~1k lines with the dnd-kit and virtualization code we already have. The main cost of going custom: roughly one extra working session on S6.1.1 and our own zoom-scale code. If you'd rather take the head start, SVAR's MIT core is licensed so we can use it; I'd then wrap it in `features/timeline/` so it can be swapped out later.
- **Q2: Split S6.1.1 into rendering (a) and editing (b)?** Recommendation: **yes** (see §2). Alternative: one L slice.
- **Q3 (capacity semantics; touches permissions): where does capacity come from, and who may change it?** Recommendation: a workspace default (`MOMENTUM_WORKLOAD_DEFAULT_HOURS`, 30 h/week, overridable in workspace settings by an admin), a per-person weekly hours value in their own prefs (for part-timers), and per-week overrides in `capacity` (PTO days reduce that week by 1/5 each). **A person edits their own; a workspace admin edits anyone's.** The grid counts **only tasks the viewer can see**, with a "Only work you can see is counted" note. Alternative: also show an "other work" total without titles, which is more accurate but reveals that private work exists.
- **Q4 (forecast backtest and numerics):** Recommendation: **(a)** a deterministic synthetic history (`momentum seed --history`) and the metric "70–90% of backtested projects finish by their P80 date"; **(b)** implement the Monte Carlo in pure Python first and add `numpy` only if the measured nightly cost is too high (it's a ~20 MB runtime dependency, needing its own justification). Alternative for (b): add `numpy` upfront.
- **Q5 (visibility of portfolios, goals and dashboards; permissions):** Recommendation: portfolios, goals and workspace dashboards are **visible to every workspace member**, editable by their owner and workspace admins; a project dashboard follows the project's visibility and edit rights. Every row and number inside is computed **as the viewer** (a portfolio shows only the projects the viewer can see; a widget's counts exclude what they can't see), so the same dashboard can show different numbers to different people. Alternative: private-by-default portfolios/dashboards with sharing (more UI, like the project Share dialog).
- **Q6 (Phase 6 journeys):** Recommendation: add to `testing-strategy.md` §4: **J11** "Timeline: drag a task that has a dependent → cascade preview → apply → undo restores both" and **J12** "Ask for a chart → preview → add to a project dashboard → it shows on reload" (mock mode). Alternative: one combined journey.

## 5. Exit criteria (confirm or adjust)

- Timeline handles **500 tasks with dependencies** smoothly: measured against the S6.1.1 budget above in a production build, numbers in `performance.md`.
- Forecast backtest on the synthetic seed history: **70–90% of projects finish by their P80 date** (the ±10% reading proposed in Q4).
- "Ask for a chart" answers **15 fixture questions** correctly: in mock mode in `make evals`, and live on the product owner's machine (`EVALS_LIVE=1`).
- J11 and J12 pass (if Q6 is accepted).
