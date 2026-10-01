---
name: Momentum
description: Wayfinding. Work as a well-signed terminal; the light theme's world, with the Graphite dark theme as its night rendition.
colors:
  rail: "#1B1F25"
  rail-ink: "#F2F4F6"
  rail-muted: "#9AA4AF"
  rail-hover: "#262B33"
  rail-active: "#313742"
  marker: "#A3E635"
  floor: "#F3F5F7"
  surface: "#FFFFFF"
  surface-2: "#ECEFF3"
  hairline: "#D3D9E0"
  hair-soft: "#E4E8ED"
  ink: "#0E1217"
  ink-2: "#29303A"
  muted: "#56616D"
  muted-2: "#677280"
  accent: "#1B1F25"
  accent-hover: "#2C323B"
  on-accent: "#FFFFFF"
  selection: "#E6F3CF"
  focus: "#4D7C0F"
  ai-amber: "oklch(0.78 0.14 75)"
typography:
  display:
    fontFamily: "Atkinson Hyperlegible Next Variable, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Atkinson Hyperlegible Next Variable, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.25
  heading:
    fontFamily: "Atkinson Hyperlegible Next Variable, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "Atkinson Hyperlegible Next Variable, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.45
  meta:
    fontFamily: "Atkinson Hyperlegible Next Variable, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.4
  label:
    fontFamily: "Atkinson Hyperlegible Next Variable, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.01em"
  figures:
    fontFamily: "Atkinson Hyperlegible Mono Variable, ui-monospace, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "10px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "6": "24px"
  "8": "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.md}"
    height: "32px"
    padding: "0 12px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  rail-item-current:
    backgroundColor: "{colors.rail-active}"
    textColor: "{colors.rail-ink}"
    rounded: "{rounded.md}"
    height: "32px"
  list-row:
    height: "34px"
  list-row-selected:
    backgroundColor: "{colors.selection}"
---

# Design System: Momentum

> **Status (2026-10-01):** chosen in the Phase 6.5 kickoff (decision page, seed `b378367a`, "Wayfinding"). Tokens are provisional until UX1 (foundations) lands; update this file with the values that survive the build.

## Overview

**Creative north star: Wayfinding.** Momentum reads like a well-signed terminal: a dark **graphite rail** (the same material as the dark theme) carries navigation like a departure board, a bright **lime marker** says "you are here", and work happens on a crisp **white floor** where every label is legible at a glance from a scaled laptop. Signage is never decoration: it orients, then gets out of the way. The light and dark themes are one world in two lights: in dark, the floor goes graphite too and the rail sinks one step deeper.

Product principles that bind the visual system (from PRODUCT.md): the task comes first; every number is honest and clickable; AI is visible (amber ✦) and reversible; keyboard and pointer are equals with immediate feedback; one component behaves the same everywhere.

Craft bar: Linear (crisp, fast, quiet chrome) and Height / Things 3 (micro-interactions, finish).

**Anti-references:** the previous cream "Paper" light theme (washed out, no hierarchy); generic white-and-blue SaaS; cards inside cards; colour as the only carrier of meaning.

## Colors

Restrained strategy: neutrals carry the floor, graphite carries structure, **lime is the only brand colour** and appears only as the current-place marker, selection tint and focus ring. Amber stays reserved for AI; purple for dev-only mock data; status colours (ok, warn, crit, info) only for state, always with an icon or words.

- **Rail (graphite, #1B1F25):** sidebar background in both themes. Items are quiet (`rail-muted`) until hovered; the current item gets `rail-active` plus a 3 px lime marker at its leading edge.
- **Floor (#F3F5F7) / Surface (#FFFFFF):** the page and its working planes. One elevation step between them, never cards on cards.
- **Ink (#0E1217) → muted (#56616D) → muted-2 (#677280):** text hierarchy; all body and placeholder text ≥ 4.5:1 on its surface.
- **Lime:** marker `#A3E635` on graphite; on white surfaces only as tint (`selection` #E6F3CF) or the deep focus ring (#4D7C0F), never as text.
- **Project colours (`--proj-1…12`):** each project keeps one hue everywhere (sidebar dot, chip, board strip, timeline bar, chart series), like a transit line.
- **Charts:** `--chart-1…8`, validated for colour-blind separation (S6.5.1).

## Typography

One family: **Atkinson Hyperlegible Next** (variable), designed for legibility, with **Atkinson Hyperlegible Mono** for task keys, code and tabular figures. Fixed rem scale for product UI, ratio about 1.15: 12 label · 13 meta · 14 body · 16 heading · 20 title · 24 display. Weights 400 / 600 / 700 only. All numbers in tables, counts and dates use tabular figures. Sizes are chosen for an effective 1280–1536 px window: body is 14 px, not 16.

## Layout

- **Primary target:** a scaled Windows laptop, 1280–1536 × 600–730 CSS px at 100% zoom. Everything essential fits a **620 px** tall window; nothing important lives below the fold of the shell.
- **Shell:** rail 240 px (collapsible to 56 px icons), top bar 44 px, content max 1200 px for reading pages, full width for lists, board, timeline and grids.
- **Rail anatomy:** pinned header (brand, Create), scrolling middle (navigation, favorites, teams), pinned footer (profile, settings). The middle is the only part that scrolls.
- **Task pane:** docks on the right at a width that adapts to the window (min 400, max 640, default 40%); the list repacks its columns in whole steps (hide due → assignee name → avatar only) instead of truncating titles.
- **Rhythm:** 4 px base; more space above a heading than below; groups tight, separation generous.
- **Breakpoints:** ≥1280 full shell; 1024–1279 rail collapses to icons by default; <768 rail becomes a drawer, pane becomes a full-screen sheet.

## Elevation & Depth

Mostly flat and tonal: floor → surface is one step. Shadows are reserved for things that float above the work: popovers and menus (soft, offset `0 8px 24px -8px` plus a 1 px ring), the task pane (a left-edge shadow), dialogs, toasts. No glow halos, no hard offset shadows.

## Shapes

Radius 4 / 6 / 8 / 10: chips and inputs 6, buttons 6, cards and panels 8, dialogs 10. Avatars and status dots round. Hairlines are 1 px `hairline` or `hair-soft`; no coloured side borders thicker than 1 px.

## Components

- **Buttons:** primary is graphite with white text (a signage block); ghost has a 1 px hairline; text buttons for low-emphasis. All 32 px tall (28 px small); hover darkens one step; press scales to 0.97 for 80 ms; focus shows a 2 px lime-deep ring with 2 px offset.
- **Rail item:** 32 px row, icon 16 px, label 13–14 px; hover lifts to `rail-hover`; current gets `rail-active` + lime marker.
- **List row:** 34 px; hover tint; selected uses `selection` (lime tint); keyboard focus uses the focus ring inside the row.
- **Inputs:** 32 px, white on floor with a hairline; focus ring as buttons; errors in words under the field.
- **Menus and popovers:** surface white, 8 px radius, soft offset shadow, 32 px items, keyboard highlight = `surface-2`.
- **Feedback:** every action answers within 100 ms: press state, optimistic update, then a toast with Undo where undoable.
- **AI:** amber ✦ marks, `AICallout` with a dashed amber edge; never lime.

## Do's and Don'ts

- **Do** keep the rail quiet: only the current place is bright.
- **Do** show every number in tabular figures and make it open the tasks behind it.
- **Do** design and verify at 1280 × 620 first, then 1366 × 768, 1920 × 1080, tablet and phone, both themes.
- **Don't** use lime as text or as a large fill on white.
- **Don't** put cards inside cards, coloured side stripes, gradient text, or a modal where an inline edit works.
- **Don't** let a list truncate titles to make room for a pane: repack the columns.
- **Don't** reintroduce cream or paper tones in the light theme.
