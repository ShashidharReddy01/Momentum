# Performance

Budgets and how we meet them. Re-measure when changing the list, rows, or drag and drop.

## Budgets (phase-1.md S1.2.6)

| Metric | Budget |
|---|---|
| Scrolling a 2,000-task project | 60 fps on a mid laptop |
| Edit feedback (assign, complete, rename) | < 50 ms |
| Initial list render after data arrives | < 1 s |

## How to measure

1. `momentum seed --perf` adds **Load Test (2k)** (2,000 synthetic tasks in 5 sections).
2. Build the SPA and serve it from the API (production React, not the dev server):
   `cd apps/web && pnpm build`, then `MOMENTUM_SPA_DIR=apps/web/dist momentum serve --port 8000`.
3. `node tools/perf/list-perf.mjs http://localhost:8000 <cpu-slowdown>` prints API time, first-row
   time, scroll frame times (p50/p95) and edit latencies.

## Results (2026-09-23, build container, headless Chromium without GPU)

| | Before | After |
|---|---|---|
| Rows in the DOM | 2,000 | ~80 |
| List rendered (1×) | ~6 s (est.) | **0.44 s** |
| List rendered (4× CPU slowdown) | 24 s | 1.3–1.6 s |
| Scroll frame p50 / p95 (1×) | — | **17 / 17 ms (60 fps)** |
| Scroll frame p50 (4×) | 67–250 ms | 50 ms |
| Assign-to-me feedback (1×) | — | **44 ms** |
| `GET …/tasks` payload | 876 KB | ~110 KB (gzip) |

Reference point: a static, JavaScript-free copy of 2,000 rows scrolls at **117 ms/frame** at 4× in
the same browser: the 4× numbers are bounded by software painting in this headless environment. On
real hardware scrolling is composited on the GPU.

## What made the difference

1. **Virtualization** (`features/tasks/VirtualRows.tsx`): sections with more than 150 rows mount only
   the visible window (+12 rows overscan). Rows have a fixed height (36 px), so no measuring.
   Smaller sections render fully (browser find keeps working for everyday projects).
2. **No drop targets at rest**: registering a dnd-kit droppable re-renders every dnd-kit hook user.
   Row drop targets now mount only during a drag (`RowDropTarget`), so rows mounted while scrolling
   don't re-render the others.
3. **Thin row shell**: `TaskRow` holds the drag hook and passes stable refs to the memoized
   `RowBody`; drag-context churn re-renders only the shell.
4. **Lazy popovers**: the assignee/date pickers and the row menu mount only when opened.
5. **Plain avatar** (no Radix): avatars appear in every row.
6. **No forced layout per frame**: the virtualizer's offset is re-read on resize, not on every render;
   scroll updates are batched (`useFlushSync: false`).
7. **gzip** for API responses ≥ 1 KB (App Service containers don't compress for us).
8. Linear-time grouping (no array spreads inside loops).

## Timeline (S6.1.1a, 2026-09-30)

**Budget** (phase-6.md): 500 tasks with ~300 dependencies render in < 1 s after the view opens, and
scroll/pan at 60 fps. **Measure:** `momentum seed --perf` also adds **Load Test Timeline (500)**
(500 dated tasks in 5 overlapping phases, ~15 milestones, ~15 unscheduled, 303 dependencies, each
on an earlier task); build and serve as above, then
`node tools/perf/timeline-perf.mjs http://localhost:8000 <cpu-slowdown> [screenshot-dir]`.

| Build container, headless Chromium | 1× | 4× CPU slowdown |
|---|---|---|
| Tab click → first bar (incl. the lazy chunk and both API calls) | 0.45 s | **0.83 s** |
| Rows / arrows in the DOM (of 500 tasks / 303 edges) | 28 / 8 | 29 / 8 |
| Vertical scroll frame p50 / p95 | 17 / 17 ms | **17 / 33 ms** |
| Horizontal pan frame p50 / p95 | 17 / 17 ms | 17 / 17 ms |
| Timeline chunk (JS, gzip) | 7 KB | |

**What makes it cheap:** fixed 36 px rows virtualized with `@tanstack/react-virtual` (the task
column is `sticky` inside each absolutely positioned row, so both axes scroll in one container);
arrows computed per render only for edges touching the mounted rows; weekend shading is one CSS
gradient, not an element per day; `memo` rows with stable callbacks; one query each for tasks and
dependency edges (`GET /projects/{id}/dependencies`).

## Dashboards (S6.5.1, 2026-09-30)

Production build (`vite build`): the dashboards feature is its own lazy chunk (**10.9 KB gzip**), and Recharts sits in a second one, `charts` (**113 KB gzip**), fetched only when the first bar, donut or line renders (number tiles and task lists don't need it). The initial bundle contains no Recharts code (checked by searching the built `index-*.js` for its class names). Each widget is one request (`GET /dashboards/widgets/{id}/data`, or `POST /dashboards/query` for the starter layout), so a slow widget never holds the others; refetches keep the previous render at 60 % opacity.

## Forecasts (S6.5.3, 2026-10-01)

Pure-Python Monte Carlo, 10,000 runs per project: the whole backtest (20 projects, each loaded from the database and simulated) takes about 5 s including process start, so about 0.2 s per project; the nightly job is linear in active projects. `numpy` wasn't needed (kickoff: only if measured too slow).

## Rules of thumb for future work

- Anything rendered per row must be cheap to mount: no Radix roots, portals, or context providers
  unless the row is interacting with it (mount on open).
- Don't read layout (`getBoundingClientRect`, `offsetTop`) in render or per-frame effects.
- Keep row props stable (`useCallback`, ids and booleans rather than new objects) so `memo` works.
- Server responses for lists: one query, no N+1 (see `test_list_query_count`).
- Note for Phase 3: `GZipMiddleware` must not buffer streaming responses (SSE) — exclude
  `text/event-stream` when streaming lands.

## Scale to ~150 people (Phase 7 E7.1, 2026-10-05)

**Setup.** `momentum seed --scale`: 150 people, 8 teams, 60 projects, ~50,000 tasks with comments, dependencies, tags and followers. The API runs in Docker (`tools/load/serve.sh`) with `MOMENTUM_WEB_WORKERS=4` and a pool of 5 + 5 per worker, on the same Docker network as Postgres. (Docker Desktop's Windows port proxy adds ~44 ms to any query that sends more than ~6 KB, so the app must not run on the host.) Load comes from `tools/load/locustfile.py` (2–8 s think time; the mix of Home, My Tasks, project lists, task details, inbox, search, edits, comments, new tasks, dashboards and workload) and realtime from `tools/load/realtime_probe.py`. Everything shares one 14-core laptop, so leave it idle during a run: running the test suite at the same time doubled every p95.

| 75 concurrent, 5 min | Before (first run) | After |
|---|---|---|
| Requests / failures | — | 6,178 / 1 (a dropped connection in the Docker proxy) |
| Aggregate p50 / p95 | 100 / 410 ms | **52 / 190 ms** |
| Home p95 | 500 ms | 300 ms |
| My Tasks p95 | 440 ms | 240 ms |
| A project's tasks p95 | 460 ms | 190 ms |
| Search p95 | 680 ms | 340 ms |
| Workload p95 (payload) | 1,100 ms (1.2 MB) | 370 ms (150 KB grid; a row's tasks on demand) |
| Item reads p95 (task, feed, sections, inbox, dashboard) | — | 60–79 ms |
| Writes p95 (edit, comment, create) | — | 110–180 ms |
| Realtime: a change reaching 5 other tabs | ~5% never arrived | **400/400, p95 193 ms** |

Budgets per endpoint class (ADR-0010): item reads < 150 ms, list views < 400 ms, writes < 300 ms, realtime < 1 s. All are met at 75 concurrent. At 150 concurrent (twice the target) the laptop saturates at ~38 requests/s. One process handles ~18/s, hence 4 workers. The job queue kept up throughout: every job succeeded and none were waiting. Re-measure on staging before go-live (phase-8.md checklist).

**What made the difference** (each found by profiling in the container: `cProfile` plus a per-statement SQL timer):
1. **Only the columns a screen shows.** Home ranks my open tasks from five columns and loads just the top five in full. My Tasks defers descriptions. `search_tsv` is deferred on tasks, comments and projects. A project's list and the workload grid read plain rows, not ORM objects; hydrating 13,000 objects was a third of workload's time.
2. **Sum in SQL where you can.** Workload sums tasks that fall within a single week in SQL, which is most tasks and every overdue one; Python spreads only multi-week tasks (`test_the_grid_sums_match_the_tasks_spread_one_by_one` guards the equivalence). Undated counts are one grouped query.
3. **No payload nobody looks at.** The workload grid sends numbers only (`tasks_for=none`); opening a cell fetches that row's tasks.
4. **Batch per level, not per row.** `access.ancestors_of` resolves the parent chain of many subtasks in one query per level (Home, My Tasks).
5. **No write on every read.** `last_seen_at` / `last_login_at` update at most every 5 minutes, and the identity lookup is one joined query.
6. **Cheap compression.** gzip level 1: most of the size win for a fraction of the CPU.

**Scale rules** (for new list endpoints): select columns, not entities, for anything that can return more than ~100 rows; never filter in Python what SQL can; send per-row detail on demand; batch anything per row; a GET must not write. Profile in the container (`docker exec … python` with a `before/after_cursor_execute` timer), not on the Windows host.
