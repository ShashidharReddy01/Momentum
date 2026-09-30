# Phase 6: Planning and Insight

**Goal:** see and plan across time, people, and goals: timeline, overview, portfolios, goals, workload, dashboards, and forecasts.

**Exit criteria:** timeline handles 500 tasks with dependencies smoothly (budget below, measured in a production build, numbers in `performance.md`); forecast backtest on the synthetic seed history puts **70–90% of projects on or before their P80 date** (P80 ± 10 points); "ask for a chart" answers 15 fixture questions correctly (mock in `make evals`, live on the product owner's machine); J11 and J12 pass.

**Kickoff:** `phase-6-kickoff.md` (2026-09-30). All six kickoff questions answered by the product owner the same day: **every recommendation accepted**, with the instruction to aim each screen past Asana's ("the WOW factor, easy for the user to view data").

**UX bar for this phase (product owner, 2026-09-30).** Each view must be easier to read than Asana's equivalent and show something Asana can't:
- **Timeline:** the critical path is visible at a glance, the forecast cone (P50–P95) sits on the timeline instead of one guessed date, and moving a task shows the ripple (ghost bars for every dependent that would move) *before* anything is saved.
- **Workload:** overload reads in one glance (heat cells, not numbers only), and the fix is one click away (✦ Suggest rebalance → preview → apply → undo).
- **Dashboards:** ask for a chart in words; every chart is built from our tokens, readable in both themes, and clicking a bar opens the tasks behind it.
- **Everywhere:** empty states explain what to do next; nulls stay honest (no invented data); AI content keeps the amber ✦ accent.

**Build order:** S6.1.1a → S6.1.1b → S6.1.2 → S6.1.3 → S6.2.1 → S6.2.2 → S6.3.1 → S6.3.2 → S6.4.1 → S6.4.2 → S6.5.1 → S6.5.2 → S6.5.3.

---

## E6.1 Timeline

**Decision (kickoff Q1, 2026-09-30): custom SVG timeline, not SVAR React Gantt.** SVAR's MIT core leaves critical path, markers and auto-scheduling in its paid PRO edition, keeps its own store and undo alongside ours, and adds ~83 KB gzip JS + CSS with its own theme. The custom timeline reuses `@tanstack/react-virtual`, `@dnd-kit`, `useProjectTasks`/`useTaskMutations` and realtime, and draws with our tokens. No new dependency.

### S6.1.1a: Timeline rendering
**Read first:** ux-specs §4.5, design-system §2, performance.md, frontend-architecture (lazy views).
**Scope:**
- `GET /projects/{id}/dependencies`: every dependency edge between the project's tasks that the caller can see (one query).
- `features/timeline/`: lazy-loaded `TimelineView` on the project's Timeline tab. Rows are top-level tasks grouped by section (collapsible, like the list), fixed row height, virtualized; completed tasks hidden unless "Show completed".
- Bars start → due in the project colour; a due-only task is a 1-day bar; a start-only task is a 1-day bar at its start; tasks with no dates go to an **Unscheduled** tray. Overdue open bars in `--crit`, done bars muted. Milestones are diamonds. Subtask count on the bar.
- Dependency arrows (finish → start elbows); an arrow whose dependent starts before its blocker is due is drawn in `--crit` (a conflict).
- **Critical path** (longest chain of dependent open work by duration, computed client-side) highlighted on a toggle.
- Today line; weekends shaded; zoom **week / month / quarter** (buttons and `⌘+`/`⌘-`), "Today" button scrolls to now; sticky time header with months/weeks.
- A left task column with the key and title; clicking a bar or title opens the task pane.
- Empty state: "Nothing scheduled yet: add start and due dates, or drag tasks from Unscheduled" with the tray.
- `momentum seed --perf` also adds **Load Test Timeline (500)**: 500 dated tasks in 5 sections with ~300 dependencies.
**Perf budget:** 500 tasks + ~300 dependencies render < 1 s after data arrives; scroll/pan at 60 fps (production build, same method as S1.2.6).
**Size:** L
**As built (2026-09-30):** `GET /projects/{id}/dependencies` returns `{task_id, depends_on_id}` edges whose two tasks are both in the project and not deleted (an edge to another project's task is left out; the pane still lists it). Critical path = the longest chain of open, scheduled, dependent tasks by total duration (client-side, `layout.ts`); a conflict = an open dependent that starts before its open blocker's due date (same-day hand-offs allowed). Rows are top-level tasks; "Show completed" adds the latest completed page (as the list). Measured: 0.83 s to the first bar at 4× CPU slowdown, 60 fps scroll (`performance.md`); the whole view is a 7 KB gzip lazy chunk.

### S6.1.1b: Timeline editing
**Scope:** drag a bar to move (both dates shift), drag its edges to resize, drag from Unscheduled onto the timeline to schedule (1-day bar at the drop day), `←/→` nudges the focused task 1 day (`Shift` = 1 week), `J/K` move focus; edits through `useTaskMutations` (undo toasts, realtime, version conflicts as elsewhere); a drag shows the new dates in a tooltip while dragging; read-only for viewers.
**Size:** M
**As built (2026-09-30):** plain pointer events (no dnd-kit: the motion is one axis snapped to days); a press that moves < 4 px is a click and opens the task; `Esc` cancels a drag. While dragging, the task's new dates are fed back through the layout, so its arrows, conflicts and the critical path move live, with a "Sep 30 – Oct 10 · 11 days (+5 days)" label above the bar. The patch touches only the dates a task uses (`datePatch`: a due-only task stays due-only when moved; stretching a one-date task adds the other edge; a milestone moves its due date). Dropping from Unscheduled sets `due_on` (a 1-day bar) with the day column highlighted. Editors only (`my_role` admin/editor); viewers get no handles, drag or nudge. The shortcut sheet lists `←/→` and `⌘=`/`⌘-`.

### S6.1.2: Dependency-aware rescheduling
**Scope:** moving a task with dependents computes the cascade in the **tasks service** (`plan_reschedule`: every dependent that would start before its blocker's new due shifts by the same working-day delta, transitively; returns the diff without writing). The timeline shows the dependents that would move as **ghost bars** during the drag, then a `PreviewCard`-style confirm ("Move T-12 and 4 dependents?" → Apply / Only this task / Cancel). Apply is one `bulk` batch (one undo). "Only this task" applies the move alone and the conflicting arrows turn `--crit`.
**Size:** M
**As built (2026-09-30):** not the `bulk` endpoint (it applies one patch to all tasks; a cascade gives each dependent its own dates) but `tasks.plan_reschedule` / `reschedule_task`: `POST /tasks/{id}/reschedule/preview` (nothing written) and `POST /tasks/{id}/reschedule` (`cascade` default true; one undo batch). Push-only (moving earlier never pulls dependents), calendar days, open and scheduled dependents only, same-day hand-off allowed, ≤ 500 tasks. A dependent the caller can only view is listed as not moved (`skipped`); one in a project they can't see is only counted (`hidden_skipped`), never named. The timeline draws dashed ghost bars from a client twin of the planner (`cascadeOf`) while dragging ("· 2 tasks follow"), asks the server only when a task's end moves later, and shows a confirm dialog (**Move all N** / **Only T-12** / Cancel) when anything would shift; earlier moves save straight away. Mo gets the same service as the `reschedule_task` tool (medium risk). Eval: two live-only `command` cases.

### S6.1.3: Dependency hand-offs
**Added 2026-09-30 at the product owner's request** ("if there is a template, one task depends on another to be finished, only then the next one kicks off"). Found missing: project templates drop dependencies, and nothing happens when a task's last blocker is finished.
**Scope:**
- **Templates keep dependencies:** a `project` template payload records each task's blockers by position (`depends_on: [task index]`, captured when saving as a template, including AI-drafted templates from S4.3.3); "New from template" replays them through `add_dependency` (one write path, cycle check included). Existing templates without the key keep working.
- **"You're up" hand-off:** when a task's last open blocker is completed, its assignee gets a notification (new kind `task_unblocked`, respecting notification preferences) naming the finished blocker; undoing that completion doesn't notify twice.
- **Rules trigger `task.unblocked`** (outbox event + rules vocabulary + `nl_rule` prompt, per the Phase 4 rule), so a project can automate the kick-off, e.g. "when a task is unblocked, move it to In progress".
- The list's "waiting on" icon and the timeline's arrows update live when the blocker completes.
**Size:** M
**As built (2026-09-30):** migration 0031 adds the `unblocked` notification kind (and preference, on by default). `set_completed` runs `_hand_off` after a completion: each open dependent with no open blocker left gets a `task.unblocked` event (rules trigger, agent event, realtime refresh) and its assignee a "You're up: \"Build\" is ready to start" notification; the snippet names the blocker only when both tasks are in the same project, otherwise "The last task it was waiting on is done". Undoing the completion re-blocks quietly. Templates: `dependencies` by position in the payload (captured, AI-drafted via `after` titles with `template_from_brief/v2`, replayed with `add_dependency`); `nl_rule/v5` knows the trigger. Deferred: a rules action to set the start date (the rule set has `set_due_relative` only), not needed for the hand-off itself.

## E6.2 Overview, status, portfolios

### S6.2.1: Project overview tab
**Scope:** project `start_on`, `due_on`, `brief` / `brief_text` exposed through the projects schemas and service (activity + undo; the columns exist since 0003); overview layout: brief editor (Tiptap, like the task description), key dates, progress (completed/total with a small bar), members and roles, milestones list (date, done state), status history, `✦ Draft status update` (P3), Radar risk note (P5).
**Size:** M
**As built (2026-09-30):** `PATCH /projects/{id}` takes `start_on`, `due_on`, `brief` (editors; sanitized; `brief_text` kept for search; start ≤ due); `ProjectOut` carries the dates, `ProjectDetailOut` the brief. `GET /projects/{id}/overview` returns total/completed/overdue top-level counts and milestones in one query pair. The overview is a summary strip (status, progress ring, dates with days left, next milestone) over brief + status updates and a milestones timeline + members; it refreshes live on task and project events. Found and fixed: `project.updated` events carried raw change values (a date broke JSON); now `jsonable_diff`. Mo's `get_project` includes the start date and brief. The project due date shows on the timeline as a dashed "Due" line.

### S6.2.2: Portfolios (lite)
**Scope:** migrations `portfolios`, `portfolio_items` (both with `workspace_id`); portfolio page: table of projects (owner, status, progress % (completed/total), due, latest status snippet, ✦ one-line AI summary), add/remove projects, portfolio status update draft (aggregates project statuses). **Visibility (kickoff Q5):** every workspace member can see a portfolio; owner and workspace admins edit it; each row is shown only if the viewer can see that project.
**Size:** M
**As built (2026-09-30):** migration 0032; `domain/portfolios` (create/rename/delete, add/remove project, all undoable; adding needs to see the project); `GET /portfolios[/{id}]` with rows per viewer and `hidden_projects` counted; check-ins `GET|POST /portfolios/{id}/status-updates` (sets `portfolios.status`, undoable) and `GET /portfolios/{id}/status-draft`, built in code (worst project status; counts in the title; at-risk/off-track under Slipped with their latest update, overdue work under Blockers, due in 14 days under Next; nothing invented). ✦ `POST /ai/portfolios/{id}/lines` (fast alias, `portfolio_lines/v1`, one call per table; numbers must come from the facts or the plain line is used). Mo's `get_portfolio` read tool. New realtime channel `portfolio:<id>`. Sidebar entry **Portfolios**. Found while here: `momentum/models.py` didn't register forms and templates, so autogenerate proposed dropping those tables; registered.

## E6.3 Goals (lite)

### S6.3.1: Goals
**Scope:** migrations `goals`, `goal_links` (with `workspace_id`); goals list (by period, owner) and detail (metric, progress source: manual / linked projects completion / sub-goals average), check-ins as `status_updates(entity_type='goal')`. Visible to all members; owner and admins edit (kickoff Q5).
**Size:** M
**As built (2026-09-30):** migration 0033; `domain/goals` (create/edit/delete, link/unlink project or portfolio, check-ins that can move the metric; all undoable; deleting a goal with sub-goals is refused; linking a project needs to see it). `GET /goals`, `GET /goals/{id}` (links with their own progress, `hidden_links` counted, children), `POST /goals/{id}/check-ins`. Progress computed per request for the viewer (never stored). Mo's `get_goals` read tool. Realtime channel `goal:<id>`. Sidebar entry **Goals**.

### S6.3.2: AI for goals
**Scope:** ✦ goal check-in narrative from linked work; ✦ "suggest projects that support this goal" (semantic match) → link proposals.
**Size:** S
**As built (2026-09-30):** `ai/goal_assist.py`: the check-in draft reads code-computed facts, including **pace** (share of the period gone) so "on track" means something; the model's draft is kept only if its numbers are all in the facts, else a code draft (status by the gap between progress and pace: ≤ 10 points on track, ≤ 25 at risk, else off track). Suggestions use hybrid retrieval (name first: the keyword half ANDs every word). New eval feature `goal_check_in` (1 mock + 2 live-only cases, live threshold 0.85, new `ai_draft` check).

## E6.4 Workload

### S6.4.1: Workload view
**Scope:**
- **Estimates first:** `estimate_minutes` on `TaskOut`/`TaskPatchIn` (activity + undo), an Effort field in the task pane (`3h`, `90m`, `1d` = 8h), a CSV import mapping, and `update_task`'s AI tool accepts it.
- **Capacity (kickoff Q3):** workspace default `MOMENTUM_WORKLOAD_DEFAULT_HOURS` (30 h/week, overridable by an admin in workspace settings) → a person's own weekly hours in their prefs → per-week overrides in `capacity` (`workspace_id, user_id, week_start, capacity_minutes`; PTO days reduce a week by 1/5 each). A person edits their own; a workspace admin edits anyone's. Weeks start Monday in the person's timezone.
- People × weeks grid: effort = sum of `estimate_minutes` spread over a task's working days (or task count if no estimates, toggle); heat cells (`--ok` → `--warn` → `--crit` tints by load/capacity), overload cells in crit; drag tasks between people/weeks. Counts **only tasks the viewer can see**, with a note saying so.
- Architect's `capacity_notes()` switches to this model (`CAPACITY_WARN` goes away).
**Size:** L

### S6.4.2: AI rebalancing
**Scope:** `✦ Suggest rebalance` → greedy heuristic in Python (respect assignee skills tag if present, due dates, project membership; no ILP dependency) → the model writes only the explanation → PreviewCard of reassignments/date moves → apply batch (one undo).
**Size:** M

## E6.5 Dashboards and forecasting

### S6.5.1: Dashboards
**Scope:** migrations `dashboards`, `dashboard_widgets` (with `workspace_id`); widget kinds: count, bar, line (completed over time), donut (by status/assignee/field), list (overdue); `query_spec` v1 (entity, filters, group_by, measure, time_bucket) validated by a Pydantic model and executed by a safe query builder (no raw SQL) **as the viewer**, through the same visibility clause as other bulk reads; Recharts (new dependency, lazy chunk) with tokens; clicking a bar/slice opens the matching tasks; project dashboard tab + workspace dashboards. Visibility per kickoff Q5.
**Size:** L

### S6.5.2: Ask for a chart
**Scope:** `POST /ai/dashboards/query`: NL → query spec (validated) → preview chart → "Add to dashboard"; `query_metrics` tool for Mo chat over the same executor. The 15 fixture questions are an eval feature (`chart`) with mock fixtures and at least one live-only case.
**Size:** M

### S6.5.3: Forecasting and risk score
**Scope:** migration `forecasts` (with `workspace_id`); nightly job per active project (`MOMENTUM_FORECASTS_ENABLED`): Monte Carlo (`MOMENTUM_FORECAST_RUNS`, default 10k; pure Python first, `numpy` only if measured too slow) over remaining tasks using historical team throughput (tasks/week or estimate-weighted), respecting dependencies roughly (critical chain via longest path), producing P50/P80/P95 end dates; risk score features reuse Radar's `signals()` (overdue ratio, blocked chain length, unassigned near-due, scope growth) plus forecast vs due → score + top drivers; Radar reads the stored score; the **forecast cone** (P50–P95 band with a P80 marker) on the timeline and the overview. `momentum seed --history` (deterministic synthetic history: ~20 finished projects over ~6 months) and `momentum forecast-backtest` (replay from each project's midpoint; pass = 70–90% by P80).
**Size:** L
