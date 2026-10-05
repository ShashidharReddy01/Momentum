# Phase 6.5: UI/UX revamp

**Goal (product owner, 2026-10-01):** "the best of best UI/UX experience, no matter what; every single thing near perfect." Frontend and UX only: no new features, no API changes. A complete redesign of the light theme, the dark theme (Graphite + lime) kept and refined, and every screen rebuilt to the bar set by **Linear** and **Height / Things 3**.

**Primary target (product owner):** Windows laptops with display scaling at 125% or 150% at 100% browser zoom, an effective window of **1280–1536 × 600–730 CSS px**. Every slice is verified at 1280 × 620 first, then 1366 × 768, 1920 × 1080, 1024 × 768 and 390 × 844, in both themes.

**Exit criteria:**
- Every screen in the audit list below passes at all five viewports in both themes with no clipped, overlapping or unreachable control (screenshot set committed under `docs/progress/ux-audit/`).
- WCAG 2.2 AA on the shell, list, pane, board and dialogs: contrast ≥ 4.5:1 for text, visible focus on every control, full keyboard operation (automated axe check with zero serious/critical findings + a manual keyboard pass).
- The design detector (`impeccable detect`) reports no unresolved findings on changed UI.
- `make check` and the full e2e suite green; initial JS stays ≤ 300 KB gzip.
- The product owner signs off on the light theme on their own laptop.

## Kickoff (2026-10-01)

**Answers (product owner):** primary screens are scaled Windows laptops; the light theme is redesigned completely, dark is kept and refined where something is bad; spacing, colours and fonts may change; UX improvements apply to both themes; benchmarks Linear and Height / Things 3.

**Direction (decision page, seed `b378367a`):** **Wayfinding**, chosen by the product owner and confirmed as the strongest by the reviewer: a graphite signage rail shared with the dark theme, a crisp white work floor, a lime "you are here" marker, legibility type (Atkinson Hyperlegible Next + Mono), with four disciplines carried over from the declined alternatives (one line colour per project; priority on one fixed weight/size ramp; tabular figures everywhere; grids that repack in whole cells instead of squeezing). Design contract: `DESIGN.md`. Product record: `PRODUCT.md`. Alternates shown: Instrument Panel (reviewer's pre-render pick), Plate Section, Ticket Wallet, the category standard. **Risk accepted:** a dark rail in a light theme can feel heavy; it stays quiet (only the current item is bright), and a light rail is a token change if the product owner wants it after UX2.

## Audit (2026-10-01, before any change)

Measured with Playwright on the seeded workspace (22 extra projects from `seed --history`, a realistic long sidebar) at 1280 × 620, 1536 × 730, 1366 × 768, 1440 × 900, 1920 × 1080, 1024 × 768, 390 × 844, light and dark. Screens: Home, My Tasks, Inbox, project List / Board / Calendar / Timeline / Overview / Dashboard, task pane, Portfolios, Goals, Workload, Dashboards, Agents, Ask Mo, Search, settings (Members, AI, Notifications), ⌘K palette, quick add, Create menu.

**P0: blocks work at the primary size**
1. **The sidebar never scrolls and is a fixed 795 px tall:** at 730 px (125% scaling) and 620 px (150%) the profile, settings and Admin entry are below the screen and unreachable without zooming out. Even at 1366 × 768 the brand row is jammed against the top edge and the profile row is cut in half.
2. **Create sits flush under the brand with no spacing**, reading as an overlap; its menu then covers the navigation it belongs to.

**P1: major**
3. **Light theme has no hierarchy:** cream on cream on cream (sidebar, page, cards within a few % lightness); muted text sits near 4.5:1; selection and hover barely register.
4. **Type is oversized for the target:** 16 px body and 15 px navigation at an effective 1280 px window; page headers take ~95 px; on a 620 px window a project list shows about nine rows.
5. **Opening a task crushes the list:** the pane takes a fixed 560 px; list titles truncate to a few words while the pane is mostly empty (a description placeholder ~120 px tall, large gaps).
6. **Board cards use a 3 px coloured side stripe** (a banned pattern) and "Add card" floats at the bottom of each column, far from the cards; the fourth column is clipped at 1366 px.
7. **Phone:** no access to project views or navigation beyond the drawer; the pane's activity tabs are cut off; cards waste width.
8. **Feedback is thin:** buttons have hover colour only; no press state; few transitions; row hover/selection is faint in light.

**P2: minor**
9. Home's onboarding strip mixes a sparkle icon (reads as AI) with a non-AI checklist; recent-project tiles use large letter avatars that duplicate the name.
10. Workload in "Tasks" mode shows a grid of empty-looking cells; heat tints only appear in Hours mode.
11. Agents page for a non-admin is an empty state with no next step.
12. Mixed font families (Inter + JetBrains Mono) and many one-off sizes (11, 12, 13, 14, 15, 17, 20 px) across screens.
13. Browser surfaces untouched: default scrollbars, selection colour and caret.

**Found with the showcase data (admin and member, 2026-10-01):**
14. **P0: the project list's columns don't line up.** Rows with tags, custom fields or date ranges push Assignee and Due left or right row by row, away from their headers; the list needs real columns (a grid with fixed tracks), not flowing items.
15. **P1:** a section whose tasks are all done shows only "Add task", with no "4 completed" hint; date ranges in the list truncate ("Sep 25 – Wednes…").
16. **P1 (fixed):** forecasts on the ten-year cap read as "Sep 18" with no year (see `phase-6.md`); now `growing` with no dates, and dates outside this year show the year.
17. **P2:** sub-goal periods print raw ISO dates; the header's member avatars overlap; the timeline's bar labels run into arrows and the due line, and every bar is the same project colour with no state.
18. **P2:** the inbox is a column of grey filled boxes with bullets; notification kinds read as faint prefixes rather than a scannable structure.

**What already works (keep):** realtime and undo everywhere, keyboard shortcuts and the ⌘K palette, the dark theme's palette, AI marking (amber ✦), honest empty states, the dashboard and forecast visuals from Phase 6.

## Showcase data (added 2026-10-01, product owner)

"Load data under every page with every possibility, and see it as the admin." The first audit ran on thin demo data (due dates only, few dependencies, empty inbox), which made screens like the timeline look broken (one-day bars at quarter zoom). **`momentum seed --showcase`** (`apps/api/momentum/seed_showcase.py`, tested) builds, through the services as the real people: a rich project (spans, milestones, a dependency chain with an overdue blocker, subtasks, all priorities, estimates, a very long title, recurring, approval, multi-homed, custom fields, tags, @mentions, two status updates), a private project, a marketing project with a request form, submissions and a rule, an operations project, an empty project, a portfolio with a check-in, goals (linked work, a metric, a sub-goal), workspace and project dashboards (one chart drafted from a question), capacity overrides, the starter agents and forecasts. The audit is re-run on it as **Avery (admin)**, a member (Ravi) and a project viewer.

## Slices (build order)

Slices are named UX1…UX8 to avoid colliding with S6.5.x. Each ships tokens/components first, then screens, and is verified at the five viewports in both themes with before/after screenshots.

### UX1: Foundations
Tokens for the Wayfinding light theme and the refined Graphite dark (rail, floor, surfaces, ink ramp, lime marker/selection/focus); **Atkinson Hyperlegible Next + Mono** self-hosted (replacing Inter and JetBrains Mono; one dependency swap); a fixed type scale (12/13/14/16/20/24) and weights 400/600/700; tabular figures on numbers; spacing 4 px base; radii 4/6/8/10; motion tokens (100/160/240 ms, exponential ease-out) with a reduced-motion alternative; themed scrollbars, selection, caret and focus rings; Button / IconButton / Input / Menu / Tooltip / Dialog states (hover, press 0.97, focus, disabled, loading). ADR-0005 amendment 3. `design-system.md` §2–4 rewritten.

### UX2: Shell
The rail: pinned header (brand, Create with proper spacing), a scrolling middle (navigation, favorites, teams with collapse memory), pinned footer (profile, settings, Admin); fits a 600 px window; collapses to a 56 px icon rail (⌘\\) and auto-collapses at < 1280 px; phone drawer. Top bar 44 px: breadcrumbs, search, Ask Mo, notifications; consistent page header component (title, actions, tabs) at a compact height.

### UX3: Task list and task pane
List rows 34 px, readable titles first; columns repack in whole steps when space shrinks; selection, hover and keyboard focus that read clearly; inline add. Pane: adaptive width (40%, 400–640 px, resizable, remembered), a tighter header, fields as a two-column grid, a description that grows with content, subtasks/blockers/files/activity with clear section rhythm; full-screen sheet on phones.

### UX4: Board, Calendar, Timeline
Cards without side stripes (a project dot and a quiet top edge instead), "Add card" right under the last card, columns that size to content and scroll horizontally with visible affordance; Calendar and Timeline on the new tokens with the same row heights and headers.

### UX5: Home, My Tasks, Inbox
Home as a working surface (priorities, waiting on others, recent projects as compact rows); My Tasks with clear sections and dates; Inbox with readable notifications and one-key triage.

### UX6: Planning screens
Overview, Dashboards, Portfolios, Goals, Workload (heat visible in both modes) on the new tokens, numbers in tabular figures, consistent page headers.

### UX7: AI, agents, settings, overlays
Ask Mo, agent gallery and runs, settings pages, the ⌘K palette, quick add, dialogs, menus, toasts and empty states: one vocabulary of surfaces, spacing and motion.

### UX8: Phase 6.5 exit
Full audit rerun at every viewport and theme (committed screenshot set), axe + keyboard pass, detector, e2e, bundle size, and the product owner's sign-off on their own laptop.

**As built (2026-10-05).**
- **Audit:** `tools/ux/audit.mjs` on the showcase workspace (`tools/ux/serve.sh`), as admin and as a member, at 5 viewports × 2 themes. It checks page overflow, clipped, covered and unnamed controls, axe WCAG 2.2 A/AA serious and critical, and console errors. Findings went 696 → 62 → **0 across 188 screens**; screenshots and report are in `docs/progress/ux-audit/2026-10-05/`.
- **Keyboard pass:** `tools/ux/keyboard.mjs` tabs through 12 key screens (focus visible, indicator, no traps), opens and closes ⌘K and quick add from the keyboard, and opens and closes the task pane with Space and Escape: **0 findings** (`docs/progress/ux-audit/keyboard/`). It found H43 (Escape on the list didn't close the pane) and H44 (editors had no focus indicator).
- **Detector:** `impeccable detect` on the 34 changed UI files raised 2 findings, both reviewed as the standard pattern (the hardening register's "Reviewed" section).
- **e2e:** 13/13, twice. The first run found H41: the NUL-stripping middleware ended every Ask Mo stream (P0, a regression from H1). It also found H42: the editor toolbar hid at mousedown and swallowed clicks below it.
- **Bundle:** initial JS **294 KB gzip** (budget 300; `tools/perf/bundle-budget.mjs`).
- **Gate:** `make check`'s steps run at Phase 7 exit, after this. Every finding is in `docs/progress/hardening-register.md` (H1–H44).
- **Left for the product owner:** sign off on the light theme on your own laptop (not blocking Phase 7).
