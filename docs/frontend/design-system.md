# Momentum Design System

Inherits the Care Cockpit design language (warm paper palette in `oklch`, ink text, hairlines, amber reserved for AI, purple for mock data) and adapts it to a dense, interactive work-management app.

## 1. Principles

1. **Calm density.** Lots of information, little noise. Hairlines separate; whitespace groups.
2. **Color lives in text, dots, and thin bars, never filled pills.** Named exceptions: project color chips, avatar fallbacks, board card color strips, heat grids (workload, dashboards), and the primary button.
3. **Amber means AI.** Anything authored or proposed by Mo or an agent uses the amber accent (dashed amber border + left amber bar + ✦ label). Nothing else may use amber.
4. **Purple means mock.** Only dev/test mock data uses the purple token. It never appears in production.
5. **Honest emptiness.** Nulls render as muted "—" or an EmptyState with a next action. Never invent placeholder values.
6. **Keyboard first.** Every primary action has a shortcut, and it's shown in tooltips and menus (`<Kbd>`).
7. **Motion explains, never decorates editing surfaces.** Transitions are 120–200 ms; entrance reveals only on Home/dashboards; reduced motion is respected.

## 2. Tokens (`styles/tokens.css`, scoped to `.momentum-root`)

Values are starting points, to be tuned in S0.3.1 against real screens. All pairs must pass WCAG AA (4.5:1 text, 3:1 UI).

```css
.momentum-root {
  /* Surfaces */
  --cream:      oklch(0.975 0.012 85);   /* app background */
  --cream-2:    oklch(0.955 0.014 85);   /* sidebar */
  --paper:      oklch(0.995 0.004 85);   /* cards, panes, rows */
  --paper-2:    oklch(0.975 0.006 85);   /* hover row, inputs */
  --hairline:   oklch(0.88 0.01 85);
  --hair-soft:  oklch(0.93 0.008 85);

  /* Ink */
  --ink:        oklch(0.22 0.015 60);    /* primary text */
  --ink-2:      oklch(0.35 0.012 60);
  --muted:      oklch(0.52 0.01 60);
  --muted-2:    oklch(0.66 0.008 60);

  /* AI (amber): AI-authored content ONLY */
  --amber:      oklch(0.78 0.14 75);
  --amber-hi:   oklch(0.85 0.12 80);
  --amber-2:    oklch(0.95 0.04 85);     /* AI callout background */
  --amber-ink:  oklch(0.45 0.10 60);     /* AI label text */

  /* Semantics */
  --ok:    oklch(0.58 0.12 150);  --ok-tint:   oklch(0.95 0.03 150);
  --warn:  oklch(0.70 0.14 70);   --warn-tint: oklch(0.96 0.04 80);
  --crit:  oklch(0.56 0.18 27);   --crit-tint: oklch(0.95 0.03 27);
  --info:  oklch(0.55 0.12 250);  --info-tint: oklch(0.95 0.02 250);  /* links, routing (was --route) */
  --mock:  oklch(0.55 0.18 300);  --mock-tint: oklch(0.95 0.04 300);  /* DEV ONLY */

  /* Interaction */
  --focus:        oklch(0.60 0.15 250);
  --selection:    oklch(0.93 0.03 250);
  --primary:      var(--ink);          /* primary button = solid ink */
  --primary-ink:  var(--paper);

  /* Project palette (chips, board strips): 12 hues at equal lightness */
  --proj-1: oklch(0.70 0.12 25);  --proj-2: oklch(0.72 0.12 60);  --proj-3: oklch(0.74 0.12 95);
  --proj-4: oklch(0.70 0.12 140); --proj-5: oklch(0.70 0.10 180); --proj-6: oklch(0.68 0.10 220);
  --proj-7: oklch(0.65 0.12 260); --proj-8: oklch(0.65 0.13 290); --proj-9: oklch(0.66 0.13 330);
  --proj-10: oklch(0.60 0.02 60); --proj-11: oklch(0.55 0.08 40); --proj-12: oklch(0.62 0.09 110);

  /* Type */
  --font-sans:  "Inter Variable", system-ui, sans-serif;
  --font-serif: "Fraunces Variable", Georgia, serif;
  --font-accent:"Instrument Serif", Georgia, serif;
  --font-mono:  "JetBrains Mono Variable", ui-monospace, monospace;

  /* Radius, shadow, motion */
  --r-sm: 4px; --r-md: 6px; --r-lg: 10px; --r-xl: 14px;
  --shadow-pop: 0 8px 24px -8px oklch(0.2 0.02 60 / 0.18), 0 0 0 1px var(--hairline);
  --shadow-pane: -12px 0 32px -16px oklch(0.2 0.02 60 / 0.20);
  --ease: cubic-bezier(.2,.7,.2,1); --spring: cubic-bezier(.3,1.4,.5,1);
  --dur-1: 120ms; --dur-2: 180ms; --dur-3: 260ms;

  /* Layout */
  --sidebar-w: 248px; --topbar-h: 52px; --pane-w: 560px; --askmo-w: 440px;
  --row-h: 36px; --row-h-compact: 30px;
}
.momentum-root[data-theme="dark"] { /* dark values: same hues, inverted lightness; defined in S0.3.1 */ }
```

Tailwind v4 `@theme` maps these tokens (`bg-paper`, `text-ink`, `text-muted`, `border-hairline`, `text-amber-ink`, …), so components use utilities that always resolve to tokens. **Raw hex/oklch values in components are forbidden** (lint rule via stylelint on `.css` and a custom ESLint rule for `className` strings).

## 3. Typography

| Role | Font | Size / line | Weight | Use |
|---|---|---|---|---|
| Display | Fraunces | 32/38 | 400 | Home greeting, page hero |
| Page title | Fraunces | 22/28 | 500 | Project name, page headers |
| Section title | Inter | 13/18 uppercase tracking 0.06em | 600 | `.eyebrow` labels |
| Body | Inter | 14/20 | 400 | Default text |
| Row | Inter | 13.5/20 | 400/500 | Task rows |
| Small | Inter | 12/16 | 400 | Meta, captions |
| Mono | JetBrains Mono | 12/16 tabular | 500 | `T-123`, dates in cells, numbers, timestamps |
| Mo voice | Instrument Serif italic | 15/22 | 400 | Mo's one-line headers ("Here's what changed") only |

## 4. Core components (all in `components/ui` or `components/common`)

| Component | Notes |
|---|---|
| `Button` | `primary` (solid ink; amber *only* when the button runs an AI action), `ghost` (hairline border), `text`, `danger`. Sizes `sm`/`md`. Loading state with spinner. |
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
| `PreviewCard` | List of proposed changes (diff rows: entity, field, old → new), risk indicator, Apply / Edit / Cancel |
| `MockBadge`, `MockOutline` | Purple, dev only |
| `Ledger` / `StatStrip` | Hairline-separated numeric stats (Care Cockpit `.ledger`) |
| `ScoreRing`, `ProgressBar` (thin), `Sparkline` | Bespoke SVG using tokens |
| `CommandPalette` | cmdk |
| `RichTextEditor` | Tiptap with mentions (`@person`, `#task`, `+project`), slash menu, paste-as-markdown |

## 5. Patterns

- **Row:** 36 px height, hover `paper-2`, selected `selection`, focus ring on the keyboard-focused row, hairline bottom border. Columns: check · title (+subtask count, comment count icons) · assignee · due · fields… · (hover) quick actions.
- **Pane:** slides in from the right (`--pane-w`, resizable 420–900 px), `--shadow-pane`, header actions (complete, like, attach, subtasks, link, more, close), body sections separated by eyebrow labels.
- **AI in context:** AI results appear as `AICallout` *inline where the user asked* (task pane, project header, inbox), never as modal takeovers.
- **Undo everywhere:** every mutation toast offers Undo; `⌘Z` triggers the last undo when focus isn't in a text field.
- **Empty project:** EmptyState with "Add task", "Import", "✦ Generate from a brief".
- **Loading:** skeletons matching final layout; never block the shell.

## 6. Breakpoints and responsiveness

`sm 640 · md 900 · lg 1200 · xl 1440`. Below `md`: the sidebar becomes a drawer, the task pane goes full-screen, and board columns scroll horizontally. Below `sm`: My Tasks and Inbox are optimized as the primary mobile screens (PWA in Phase 8).

## 7. Iconography

lucide-react through `<Icon name="…" />` with defaults: size 16 (inline) / 18 (buttons), `strokeWidth 1.7`, `currentColor`. The AI mark is a custom ✦ sparkle SVG (`<MoMark/>`), used only with amber.

## 8. Voice and copy

- Plain, short, human. "Due Friday", not "Due date: 2026-09-26".
- Mo speaks in first person, briefly, and always says what it did or proposes: "I drafted a status update from 14 changes this week."
- Errors say what happened and what to do next. Never blame the user.
