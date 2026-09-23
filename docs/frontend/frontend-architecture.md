# Frontend Architecture

## 1. Lineage: what we keep from Care Cockpit and what we change

The previous app (Care Cockpit) is a strong base for **design language and conventions**. Momentum is an **editing-heavy, realtime, keyboard-driven** app (inline edits, drag and drop, rich text, menus everywhere), while Care Cockpit is mostly **read-oriented dashboards**, so parts of its engineering foundation need upgrading.

| Care Cockpit | Momentum decision | Why |
|---|---|---|
| React 19 + TS strict + Vite + `@/` alias | **Keep** | Same foundation you know |
| React Router 6, flat route table under one `<Layout/>` | **Keep the pattern, upgrade to React Router 7** (library/data mode) | Nearly identical API; loaders/lazy routes; continued support |
| `Layout` = Sidebar + TopBar + `<Outlet/>` + persistent AI slide-over | **Keep**: Sidebar + TopBar + Outlet + **Task pane** + **Ask Mo panel** | The proven shell becomes Asana's shell |
| One ~1000-line global CSS organized by page | **Change**: tokens in CSS variables + Tailwind v4 utilities mapped to tokens (`@theme`) + small component CSS where needed | Page-organized global CSS doesn't scale to ~60 components and leaks into host apps when embedded |
| `oklch()` custom-property palette (cream/paper/ink/hairline…) | **Keep the cream palette for light mode ("Paper", ink accent)**; dark mode is **"Graphite"** (charcoal + lime). Tokens renamed semantically (`canvas`, `surface`, …), scoped to `.momentum-root` | Chosen on the real UI after comparing options (ADR-0005 amendment 2) |
| "Color lives in text and thin bars, never filled pills" | **Keep** as a principle with named exceptions (project color chips, heat grids, workload) | Calm UI for a dense app |
| **Amber = AI-authored content only** | **Keep, strictly** | Maps perfectly to "AI drafts, humans confirm" |
| **Purple = mock data** (MockBadge) | **Keep, dev-only**. In production builds, mock UI is compiled out. | Honesty without silent fallbacks |
| Nulls shown as empty states, never fabricated | **Keep** as a rule | |
| Fonts: Fraunces / Instrument Serif / Inter / JetBrains Mono from Google Fonts | **Inter only + JetBrains Mono**, self-hosted via `@fontsource`. Drop the display serif and the italic "AI voice" | One sans with weight-based hierarchy is how serious work tools read; self-hosting works on office networks |
| No UI library; hand-built everything | **Change**: Radix primitives (via shadcn/ui source, restyled to our tokens) for menus, popovers, dialogs, comboboxes, tooltips, tabs | Accessibility and keyboard behavior of menus/popovers/date pickers is hard to get right by hand, and Momentum needs dozens of them |
| Hand-drawn SVG icons | **Change**: `lucide-react` with the same visual spec (24 viewBox, 1.7 stroke, round caps) through one `<Icon>` wrapper; custom SVGs only for brand/special marks | Hundreds of icons needed |
| Hand-drawn SVG charts (ScoreRing, arcs) | **Keep for small bespoke visuals** (ScoreRing, sparklines, progress). **Recharts** for dashboard charts (Phase 6) | |
| Plain `fetch` + `useEffect` + local state per page | **Change**: typed client (`openapi-fetch` + generated `schema.d.ts`) + **TanStack Query** (cache, optimistic updates, realtime invalidation) | Required for realtime + optimistic editing |
| One env var `VITE_PERFORMANCE_API_BASE` reused everywhere, default `http://localhost:8420` | **Change**: same-origin relative API (`{basePath}/api/v1`), runtime config endpoint; Vite dev proxy | Works behind Easy Auth and when embedded |
| `credentials: 'include'` cookie sessions | **Keep** (same-origin) + CSRF header | |
| `?actingAs=<email>` request scoping | **Remove** | Identity must come from the server session only |
| Per-domain `*Api.ts` files with interfaces + mapping functions (`mapOpenCase`…) | **Keep the idea**: `features/<x>/api.ts` wraps generated types; mappers only where the UI model differs | Types generated, not hand-written |
| `usePerformanceData` silent mock-fallback on *any* error | **Change**: explicit error states in production; **MSW** (Mock Service Worker) for dev/test mocks, visibly flagged | Silent fallbacks hide outages |
| No state library | **Add Zustand** for cross-cutting UI state (selection, pane, command bar, keyboard focus) | Many components share it |
| No tests | **Add** Vitest + Testing Library + MSW + Playwright | |
| Ad-hoc breakpoints (1300/1200/1100/1080/900/820) | **Tokenize**: `sm 640 · md 900 · lg 1200 · xl 1440` | |
| Two tab idioms (underline, segmented) | **Keep both** as named components: `Tabs` (views) and `Segmented` (sub-modes) | Each has a defined use |
| `.reveal` staggered entrance animations, uppercase `.eyebrow` labels | **Drop.** Motion only for state changes; sentence-case `section-label` | Decorative motion and uppercase eyebrows are part of the generic-AI look |

**Verdict (final, 2026-09-23):** keep Care Cockpit's principles and its cream palette as the light theme ("Paper"). Add a charcoal + lime dark theme ("Graphite"). Drop the decorative serifs, italic AI voice, uppercase eyebrows and reveal animations. The engineering layer is upgraded for an interactive, realtime, embeddable app.

## 2. Stack

| Concern | Choice |
|---|---|
| Build | Vite (latest stable at scaffold), `@vitejs/plugin-react`, TS 5.x strict |
| Routing | React Router 7 (data router, lazy routes) |
| Server state | TanStack Query v5 |
| API client | `openapi-typescript` (types) + `openapi-fetch` (typed fetch) |
| UI state | Zustand v5 (slices: `ui`, `selection`, `commandBar`, `pane`) |
| Styling | Tailwind v4 (`@tailwindcss/vite`) + tokens in `styles/tokens.css` + `@theme` mapping |
| Primitives | Radix UI via shadcn/ui source in `momentum/components/ui/*` (owned, restyled) |
| Icons | lucide-react via `<Icon name=… />` |
| Rich text | Tiptap (StarterKit, Mention, Link, TaskItem, Placeholder) |
| DnD | dnd-kit (core + sortable) |
| Virtualization | TanStack Virtual |
| Tables | TanStack Table (list view columns) |
| Dates | date-fns + chrono-node (NL parsing), user timezone aware |
| Command palette | cmdk |
| Charts | Recharts (Phase 6) + bespoke SVG |
| Toasts | sonner (restyled) |
| Mocks | MSW v2 |
| Tests | Vitest, @testing-library/react, user-event, Playwright |
| Lint | ESLint (typescript-eslint, react-hooks, jsx-a11y, import order), Prettier |

## 3. Folder structure

```
apps/web/
├── index.html
├── vite.config.ts            # alias @ → src/momentum, dev proxy /api /ws /dev /auth → :8000
├── src/
│   ├── main.tsx              # standalone bootstrap
│   └── momentum/
│       ├── index.ts          # public exports for embedding
│       ├── MomentumApp.tsx   # <MomentumProvider><RouterProvider/></MomentumProvider>
│       ├── routes.tsx        # route objects (lazy)
│       ├── providers/        # MomentumProvider (config, QueryClient, WS, theme, toasts)
│       ├── shell/            # Layout, Sidebar, TopBar, TaskPaneHost, AskMoPanel, CommandBar
│       ├── features/
│       │   ├── auth/         # useMe, login redirect, session-expired banner
│       │   ├── home/  my-tasks/  inbox/  search/
│       │   ├── projects/     # project header, views switcher, overview, settings
│       │   ├── tasks/        # list view, task row, task pane, subtasks, pickers
│       │   ├── board/  calendar/  timeline/  workload/  dashboards/
│       │   ├── comments/  activity/  attachments/  fields/  tags/
│       │   ├── ai/           # AskMo chat, preview cards, inline AI actions, AI badges
│       │   ├── agents/  rules/  forms/  templates/  goals/  portfolios/
│       │   └── admin/
│       │   (each feature: api.ts · queries.ts (query keys + hooks) · components/ · types.ts · *.test.tsx)
│       ├── components/
│       │   ├── ui/           # Radix-based primitives (Button, Popover, Menu, Dialog, …)
│       │   └── common/       # EmptyState, ErrorState, AICallout, MockBadge, ScoreRing, Ledger, Avatar…
│       ├── lib/
│       │   ├── api/          # client.ts (openapi-fetch + CSRF header + 401 handling), schema.d.ts (generated), errors.ts
│       │   ├── realtime/     # ws client, subscriptions, handlers.ts
│       │   ├── sse.ts        # POST-SSE reader for AI streams
│       │   ├── dates.ts  keyboard.ts  ordering.ts  format.ts
│       │   └── config.ts     # useMomentumConfig
│       ├── stores/           # zustand slices
│       ├── styles/           # tokens.css, base.css (scoped reset), fonts.css, index.css (@import tailwind, @theme)
│       └── mocks/            # MSW handlers + fixtures (dev/test only)
└── e2e/                      # Playwright specs
```

## 4. Data layer patterns

**Query keys** (one factory per feature):
```ts
export const taskKeys = {
  all: ['tasks'] as const,
  detail: (id: string) => ['tasks', id] as const,
  byProject: (projectId: string) => ['projects', projectId, 'tasks'] as const,
  mine: () => ['me', 'tasks'] as const,
};
```

**Optimistic mutation template:**
```ts
export function useUpdateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; patch: TaskPatch }) => api.PATCH('/tasks/{id}', { params: { path: { id: v.id } }, body: v.patch }),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: taskKeys.detail(id) });
      const prev = qc.getQueryData(taskKeys.detail(id));
      qc.setQueryData(taskKeys.detail(id), (t) => t && { ...t, ...patch });
      patchTaskInLists(qc, id, patch);
      return { prev };
    },
    onError: (_e, { id }, ctx) => { qc.setQueryData(taskKeys.detail(id), ctx?.prev); toastError(_e); },
    onSuccess: (res) => showUndoToast(res.meta.activity_id),
  });
}
```

**Errors:** `lib/api/errors.ts` turns problem+json into `ApiError {status, code, detail, fieldErrors}`. On 401, the global handler triggers the session-expired flow. Pages render explicit `ErrorState` (never mock data in production).

**Realtime:** `MomentumProvider` opens one WS. Features subscribe with `useChannel('project:'+id)`. `handlers.ts` updates caches (see `architecture/realtime-jobs-events.md` §4).

**Mock/dev data:** MSW handlers exist for component development and tests. When MSW is active in dev, a global purple "Mock data" ribbon is shown. MSW isn't bundled in production (`import.meta.env.DEV` guard + dynamic import).

## 5. State ownership

| State | Where |
|---|---|
| Server data | TanStack Query only (never copied into Zustand) |
| Selection (multi-select task ids), focused row | `stores/selection` |
| Open task pane, Ask Mo panel, command bar | URL for the task pane (`?task=<id>` or `/task/:id`), Zustand for panels |
| Filters/sort/group per project view | URL search params (shareable) + user prefs saved via API |
| Drafts (comment/description in progress) | localStorage keyed by entity id (survives session expiry) |

## 6. Routing table

| Path | Screen |
|---|---|
| `/` | Home |
| `/my-tasks` | My Tasks |
| `/inbox` | Inbox |
| `/ask` | Ask Mo (full page) |
| `/search?q=` | Search results |
| `/projects/:projectId/:view?` (`list`\|`board`\|`calendar`\|`timeline`\|`overview`\|`dashboard`) | Project |
| `…?task=:taskId` (on any route) | Task pane over current screen |
| `/task/:taskId` | Full-page task (deep link fallback) |
| `/teams/:teamId` | Team page |
| `/agents`, `/agents/:agentId`, `/agents/runs/:runId` | Agents |
| `/rules`, `/forms/:formId`, `/f/:publicToken` (public form) | Workflow |
| `/portfolios/:id`, `/goals`, `/goals/:id`, `/dashboards/:id`, `/workload` | Planning |
| `/settings/*` (profile, notifications, tokens) · `/admin/*` (members, AI, agents, integrations, jobs) | Settings |
| `/dev/login` | Dev-only login picker |

## 7. Performance budgets

- Initial JS ≤ 300 KB gz for the shell + list view. Board, timeline, dashboards, editor, and charts are lazy.
- List view: 2,000 tasks with virtualization at 60fps scroll; inline edit feedback < 50 ms (optimistic).
- Avoid re-render storms: row components are memoized by `task.id + version`; selection uses subscribe-by-id selectors.

## 8. Accessibility

- All interactive elements are reachable by keyboard; Radix gives focus management for menus and dialogs.
- Visible focus ring token (`--focus`). Contrast AA minimum (checked in the design-system doc).
- `aria-live` for toasts and AI streaming status; reduced-motion respected.
- `jsx-a11y` lint rules on; Playwright runs axe checks on key pages (Phase 8).
