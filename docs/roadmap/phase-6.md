# Phase 6: Planning and Insight

**Goal:** see and plan across time, people, and goals: timeline, overview, portfolios, goals, workload, dashboards, and forecasts.

**Exit criteria:** timeline handles 500 tasks with dependencies smoothly; forecast backtest on seed history shows P80 calibration within ±10%; "ask for a chart" answers 15 fixture questions correctly.

---

## E6.1 Timeline

### S6.1.1: Timeline view
**Scope:** rows grouped by section; bars start→due (tasks with only due → 1-day bar; no dates → "unscheduled" tray); milestones as diamonds; dependency arrows; today line; zoom week/month/quarter; drag to move and resize edges; keyboard nudge (`←/→` 1 day).
**Decision at kickoff:** SVAR React Gantt vs custom SVG (evaluate licensing, bundle size, and styling control with tokens).
**Size:** L

### S6.1.2: Dependency-aware rescheduling
**Scope:** moving a task with dependents proposes shifting them (preview of the cascade, apply as one batch, undoable); option "keep dependents fixed" highlights conflicts in crit.
**Size:** M

## E6.2 Overview, status, portfolios

### S6.2.1: Project overview tab
**Scope:** brief editor, members and roles, milestones list, status history, project dates, `✦ Draft status update` (from P3), Radar risk note (from P5).
**Size:** M

### S6.2.2: Portfolios (lite)
**Scope:** migrations `portfolios`, `portfolio_items`; portfolio page: table of projects (owner, status, progress % (completed/total), due, latest status snippet, ✦ one-line AI summary), add/remove projects, portfolio status update draft (aggregates project statuses).
**Size:** M

## E6.3 Goals (lite)

### S6.3.1: Goals
**Scope:** migrations `goals`, `goal_links`; goals list (by period, owner) and detail (metric, progress source: manual / linked projects completion / sub-goals average), check-ins as status updates.
**Size:** M

### S6.3.2: AI for goals
**Scope:** ✦ goal check-in narrative from linked work; ✦ "suggest projects that support this goal" (semantic match) → link proposals.
**Size:** S

## E6.4 Workload

### S6.4.1: Workload view
**Scope:** migration `capacity`; people × weeks grid; effort = sum of `estimate_minutes` (or task count if no estimates, toggle); capacity from settings (default 30h/week, PTO days reduce it: manual entry now, calendar in P7); overload cells in crit; drag tasks between people/weeks.
**Size:** L

### S6.4.2: AI rebalancing
**Scope:** `✦ Suggest rebalance` → greedy/ILP heuristic in Python (respect assignee skills tag if present, due dates, project membership) → PreviewCard of reassignments/date moves → apply batch.
**Size:** M

## E6.5 Dashboards and forecasting

### S6.5.1: Dashboards
**Scope:** migrations `dashboards`, `dashboard_widgets`; widget kinds: count, bar, line (completed over time), donut (by status/assignee/field), list (overdue); query spec JSON (entity, filters, group_by, measure, time_bucket) executed by a safe query builder (no raw SQL); Recharts with tokens; project dashboard tab + workspace dashboards.
**Size:** L

### S6.5.2: Ask for a chart
**Scope:** `POST /ai/dashboards/query`: NL → query spec (validated) → preview chart → "Add to dashboard"; `query_metrics` tool for Mo chat.
**Size:** M

### S6.5.3: Forecasting and risk score
**Scope:** migration `forecasts`; nightly job per active project: Monte Carlo (10k runs) over remaining tasks using historical team throughput (tasks/week or estimate-weighted), respecting dependencies roughly (critical chain via longest path), producing P50/P80/P95 end dates; risk score features (overdue ratio, blocked chain length, unassigned near-due, scope growth, forecast vs due) → score + top drivers; Radar agent consumes it; forecast marker on timeline and overview. Backtest script against seed history.
**Size:** L
