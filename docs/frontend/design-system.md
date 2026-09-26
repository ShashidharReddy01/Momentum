# Momentum Design System

Two themes, one system:
- **Light = "Paper":** warm cream surfaces, ink text, and **ink as the brand accent** (solid ink primary buttons, ink brand mark).
- **Dark = "Graphite":** charcoal surfaces with a **lime signal accent**.

**Amber is reserved for AI** in both themes, and **purple marks dev-only mock data**. Typography is Inter throughout, with JetBrains Mono for keys and numbers. Theme choice: user menu → Light (Paper) / Dark (Graphite); the default follows the OS preference. See ADR-0005 amendments for how we got here.

## 1. Principles

1. **Calm density.** Lots of information, little noise. Hairlines separate; whitespace groups; hierarchy comes from weight and size, not from decorative fonts.
2. **One accent per theme.** Ink (light) or lime (dark) for primary actions and the brand mark. Nothing else competes with it.
3. **Color lives in text, dots, and thin bars, never filled pills.** Named exceptions: the primary button, project color chips, avatar fallbacks, board card color strips, heat grids (workload, dashboards).
4. **Amber means AI.** Anything authored or proposed by Mo or an agent uses the amber treatment (dashed amber border + left amber bar + ✦ label). Nothing else may use amber.
5. **Purple means mock.** Only dev/test mock data uses the purple token. It never appears in production.
6. **Honest emptiness.** Nulls render as muted "—" or an EmptyState with a next action. Never invent placeholder values.
7. **Keyboard first.** Every primary action has a shortcut, shown in tooltips and menus (`<Kbd>`).
8. **Motion is functional.** 100–160 ms transitions for state changes (panes, menus, completion). No decorative entrance animations. Reduced motion is respected.

## 2. Tokens (`styles/tokens.css`, scoped to `.momentum-root`)

| Group | Tokens | Light · Paper (oklch) | Dark · Graphite (oklch) | Use |
|---|---|---|---|---|
| Surfaces | `--canvas`, `--sidebar`, `--surface`, `--surface-2` | 0.975 0.012 85 / 0.955 0.014 85 / 0.995 0.004 85 / 0.972 0.007 85 | 0.205 / 0.17 / 0.24 / 0.275 (hue 255, chroma ≈0.007) | App background, sidebar, cards/panes/rows, hover/inputs |
| Lines | `--hairline`, `--hair-soft` | 0.88 / 0.93 | 0.32 / 0.28 | Borders, dividers |
| Ink | `--ink`, `--ink-2`, `--muted`, `--muted-2` | 0.22 / 0.35 / 0.50 / 0.64 (warm) | 0.95 / 0.86 / 0.68 / 0.56 | Text hierarchy |
| Sidebar | `--sidebar-ink`, `--sidebar-muted`, `--sidebar-hover`, `--sidebar-active`, `--sidebar-line` | from ink/surfaces | own values | Sidebar can diverge from content |
| Accent | `--accent`, `--accent-hover`, `--accent-tint`, `--on-accent` | **ink** 0.22 0.015 60 on cream | **lime** 0.87 0.18 128 with dark text | Primary buttons, brand mark, focus (dark) |
| AI | `--amber`, `--amber-hi`, `--amber-2`, `--amber-ink` | 0.78 0.14 75 … | 0.80 0.14 75 … | **AI content only** |
| Status | `--ok`, `--warn`, `--crit`, `--info` (+ `-tint`) | | | Due/overdue text, status dots |
| Mock | `--mock`, `--mock-tint` | 0.52 0.18 300 | 0.75 0.15 300 | **Dev only** |
| Interaction | `--focus`, `--selection` | blue focus, soft blue selection | lime focus, lime-tinted selection | |
| Projects | `--proj-1` … `--proj-12` | 12 hues at matched lightness | same | Project chips, avatars |
| Shape | `--r-sm 4`, `--r-md 6`, `--r-lg 8`, `--r-xl 12`; `--shadow-pop`, `--shadow-pane` | | | |
| Layout | `--sidebar-w 240`, `--topbar-h 48`, `--pane-w 560`, `--askmo-w 420`, `--row-h 36` | | | |

Tailwind v4 `@theme inline` maps tokens to utilities (`bg-canvas`, `bg-surface`, `text-ink`, `text-muted`, `border-hairline`, `bg-accent`, `text-on-accent`, `bg-sidebar`, `text-sidebar-ink`, `text-amber-ink`, …). **Raw color literals in components are forbidden** (ESLint rule). Never hard-code "dark means lime" in components; always use `accent`.

## 3. Typography

One family: **Inter** (variable, self-hosted), plus **JetBrains Mono** for keys, numbers, and timestamps.

| Role | Class | Size / line | Weight |
|---|---|---|---|
| Page title | `page-title` | 20/28, tracking −0.01em | 600 |
| Section title | `text-[15px] font-semibold` | 15/22 | 600 |
| Card / group title | `text-[13px] font-semibold` | 13/18 | 600 |
| Section label (sidebar groups, menu labels) | `section-label` | 12/16, sentence case | 600, muted |
| Body | default | 14/20 | 400 |
| Row text | `text-[13.5px]` | 13.5/20 | 400 (500 for emphasis) |
| Meta | `text-[13px] text-muted` / `text-xs` | 13/18, 12/16 | 400 |
| Mono | `font-mono tabular` | 12/16 | 500 |

Mo's text uses the same typography as everything else. Its identity comes from the amber AI container and the ✦ mark, not from a different font.

## 4. Core components (all in `components/ui` or `components/common`)

| Component | Notes |
|---|---|
| `Button` | `primary` (solid accent: ink in light, lime in dark), `sidebar` (on the sidebar), `ai` (amber, *only* for buttons that run an AI action), `ghost` (hairline border), `text`, `danger`. Sizes `sm`/`md`/`icon`. Loading state with spinner. |
| `IconButton` | Always has `aria-label` + tooltip with shortcut |
| `Input`, `Textarea`, `NumberInput` | Paper-2 background, hairline border, focus ring |
| `Select`, `Combobox` | Radix; searchable; used by pickers |
| `AssigneePicker`, `DatePicker` (NL input "next fri" + calendar), `ProjectPicker`, `SectionPicker`, `TagPicker`, `FieldValueEditor` | Domain pickers built on Combobox/Popover |
| `Popover`, `DropdownMenu`, `ContextMenu`, `Dialog`, `Sheet` (slide-over), `Tooltip` | Radix, portaled into `.momentum-root` |
| `Tabs` (underline, for views) and `Segmented` (sub-modes) | Two named idioms, not interchangeable |
| `Toast` | With Undo action for mutations (5s), error toasts with retry |
| `Avatar`, `AvatarStack` | Agents get a ✦ amber ring |
| `CompleteCheck` | Circular task checkbox with completion animation |
| `StatusDot`, `PriorityText`, `DueText` | Color in text/dot only: overdue = crit text, today = warn, done = muted strikethrough |
| `Kbd` | Keyboard hint |
| `Skeleton` | Row, pane, and card skeletons (no spinners for page loads) |
| `EmptyState` | Icon + title + one-line explanation + primary action |
| `ErrorState` | Human message + retry + request id (copyable) |
| `AICallout` | Dashed amber border, left amber bar, ✦ "Mo" label, content, actions (Apply / Edit / Dismiss), feedback 👍/👎 |
| `AIBadge` | Small ✦ marker on AI-authored comments, fields, status updates; tooltip "Drafted by Mo · why?" |
| `MoText` + citation chips | **S3.3.1 (`features/ai/MoThread.tsx`):** Mo's answers render a safe Markdown subset as React nodes (paragraphs, `- ` bullets, `**bold**`; never raw HTML). `[T-12]` becomes a small mono chip linking to the task (`/task/:id`, accessible name "T-12 <title>"), `[P:Name]` a chip to the project, **only when the server resolved it as valid for the reader**; anything else stays muted plain text with a "can't open" tooltip. Under a chat answer: "No sources from your workspace cited." when nothing resolved, and 👍/👎 (`aria-pressed`). `MoThread` (runs: question bubble, activity line, answer, PreviewCard, clarify chips, error) and `MoComposer` are shared by the Ask Mo panel and `/ask`. |
| `AskMoButton` | **S3.3.2 (`components/common/AI.tsx`):** ghost button with the Mo mark ("Ask Mo", or mark only in tight headers), accessible name "Ask Mo about this task/project" / "…about these tasks". Opens the Ask Mo panel on a new chat pinned to it; the panel shows an "About …" chip with × (unpin) and starter-question chips (`Suggested questions`) when the chat is empty. Renders nothing while AI is off. |
| Writing help (editor) | **S3.4.4 (`components/editor/WritingHelp.tsx`):** a "✦ Mo" menu at the end of the editor toolbar (Improve, Make shorter, Fix spelling & grammar; Tone; Translate to). The suggestion appears as an AI callout between toolbar and text ("Mo suggests: Shorter", Replace / Try again / Reject); nothing changes until Replace. The editor takes the AI call as a `writingHelp` prop, so `components/` never calls the API. |
| `PreviewCard` | List of proposed changes (diff rows: entity, field, old → new), risk indicator, Apply / Edit / Cancel. **As built (S3.1.3, `features/ai/PreviewCard.tsx`):** an `AICallout` labeled "Mo suggests"; changes grouped by entity label (`T-12 Draft copy`) with one readable line per field (`Due: — → 2026-10-09`, ordering keys never shown); risk chip (ok / warn / crit tints); high risk opens a confirm `Dialog` ("Apply N changes?", Go back / Yes, apply) before anything is sent; a stale target shows a warn notice and the updated diff instead of applying; after applying, a toast with Undo for the whole action; decided suggestions keep their diff and show their state (Applied / Dismissed / expired / Undone / failed + reason) with no buttons. `Edit` appears only when the host passes `onEdit` (⌘K puts the request back in the input, S3.2.2). Also reachable at `/ai/actions/:id`. |
| `MockBadge`, `MockOutline` | Purple, dev only |
| `Ledger` / `StatStrip` | Hairline-separated numeric stats |
| `BrandMark` | Momentum logo (accent square with M stroke: ink in light, lime in dark) |
| `ScoreRing`, `ProgressBar` (thin), `Sparkline` | Bespoke SVG using tokens |
| `CommandPalette` | cmdk |
| `RichTextEditor` | Tiptap with mentions (`@person`, `#task`, `+project`), slash menu, paste-as-markdown |

## 5. Patterns

- **Row:** 36 px height, hover `paper-2`, selected `selection`, focus ring on the keyboard-focused row, hairline bottom border. Columns: check · title (+subtask count, comment count icons) · assignee · due · fields… · (hover) quick actions.
- **Pane:** slides in from the right (`--pane-w`, resizable 420–900 px), `--shadow-pane`, header actions (complete, like, attach, subtasks, link, more, close), body sections separated by section labels.
- **AI in context:** AI results appear as `AICallout` *inline where the user asked* (task pane, project header, inbox), never as modal takeovers.
- **Undo everywhere:** every mutation toast offers Undo; `⌘Z` triggers the last undo when focus isn't in a text field.
- **Empty project:** EmptyState with "Add task", "Import", "✦ Generate from a brief".
- **Loading:** skeletons matching final layout; never block the shell.
- **Home:** functional, not a hero. A modest greeting title plus the date, then working widgets.

## 6. Breakpoints and responsiveness

`sm 640 · md 900 · lg 1200 · xl 1440`. Below `md`: the sidebar becomes a drawer, the task pane goes full-screen, and board columns scroll horizontally. Below `sm`: My Tasks and Inbox are optimized as the primary mobile screens (PWA in Phase 8).

## 7. Iconography

lucide-react through `<Icon name="…" />` with defaults: size 16 (inline) / 18 (buttons), `strokeWidth 1.7`, `currentColor`. The AI mark is a custom ✦ sparkle SVG (`<MoMark/>`), used only with amber.

## 8. Voice and copy

- Plain, short, human. "Due Friday", not "Due date: 2026-09-26".
- Mo speaks in first person, briefly, and always says what it did or proposes: "I drafted a status update from 14 changes this week."
- Sentence case everywhere (buttons, labels, headings). No ALL-CAPS labels.
- Errors say what happened and what to do next. Never blame the user.
