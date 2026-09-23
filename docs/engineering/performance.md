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

## Rules of thumb for future work

- Anything rendered per row must be cheap to mount: no Radix roots, portals, or context providers
  unless the row is interacting with it (mount on open).
- Don't read layout (`getBoundingClientRect`, `offsetTop`) in render or per-frame effects.
- Keep row props stable (`useCallback`, ids and booleans rather than new objects) so `memo` works.
- Server responses for lists: one query, no N+1 (see `test_list_query_count`).
- Note for Phase 3: `GZipMiddleware` must not buffer streaming responses (SSE) — exclude
  `text/event-stream` when streaming lands.
