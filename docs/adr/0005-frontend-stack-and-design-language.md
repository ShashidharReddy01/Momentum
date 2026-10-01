# ADR-0005: Frontend stack and design language
- **Status:** Accepted · **Date:** 2026-09-23
## Context
The builder has a prior app (Care Cockpit: React 19, Vite, TS, RR6, one global CSS design system with oklch tokens, amber-for-AI, purple-for-mock, plain fetch). Momentum is editing-heavy, realtime, keyboard-driven, and must be embeddable.
## Decision
Keep Care Cockpit's design language (tokens, fonts (self-hosted), amber = AI, purple = mock, honest empty states, shell + AI slide-over). Upgrade engineering: React Router 7, TanStack Query, openapi-fetch generated types, Zustand for UI state, Tailwind v4 mapped to tokens, Radix primitives via shadcn (owned source), lucide icons, dnd-kit, Tiptap, MSW, Vitest, Playwright. Styles are scoped to `.momentum-root`.
## Alternatives
Pure global CSS (doesn't scale, leaks when embedded); a full component library like MUI (heavy, hard to match the design language).
## Consequences
A distinctive look separate from Asana's visuals with an Asana-like layout; accessible primitives; realtime-ready data layer. More dependencies than Care Cockpit, each justified.

## Amendment (2026-09-23): visual style
After seeing the shell running, we reviewed the inherited visual style honestly. Cream paper backgrounds, Fraunces display serif, an Instrument Serif italic "AI voice", uppercase eyebrow labels, and staggered reveal animations together form a recognizable generic AI-generated look, and they suit landing pages more than an all-day work tool.
**Decision:** keep the principles (amber = AI only, purple = mock, honest empty states, hairlines over pills, token system, scoped styles). Replace the style with neutral cool surfaces (`canvas`/`surface` tokens), Inter-only typography with weight-based hierarchy, one blue brand accent (primary actions, selection, focus, links), sentence-case labels, and functional motion only. Implemented before Phase 1, while only the shell existed, so the cost was a token and font swap.

## Amendment 2 (2026-09-23): final themes
The neutral white + blue restyle from Amendment 1 was rejected: it read as a generic SaaS template. We compared five colored directions on the real UI (petrol, aubergine, indigo, forest, graphite).
**Decision:** Dark = **Graphite** (charcoal + lime accent). Light = **Paper** (the original warm cream palette with ink as the accent). Typography stays Inter + JetBrains Mono in both themes. Other palettes and the palette picker were removed; light/dark is the only switch.

## Amendment 3 (2026-10-01): Wayfinding light theme, Atkinson type (Phase 6.5, UX1)
The product owner rejected the Paper light theme as washed out (cream on cream, no hierarchy) and found the type oversized on scaled Windows laptops (an effective 1280–1536 × 600–730 px window). In the Phase 6.5 kickoff they chose the **Wayfinding** direction (see `DESIGN.md`).
**Decision:** Light = **Wayfinding**: a graphite rail (the dark theme's own material), a cool `#F3F5F7` floor with white working surfaces, graphite primary buttons, and lime only as the current-place marker, the selection tint and a deep focus ring (`#4D7C0F`), never as text on white. Dark stays **Graphite + lime**, with `--marker` and `--shadow-raise` added. Typography moves from Inter + JetBrains Mono to **Atkinson Hyperlegible Next + Atkinson Hyperlegible Mono** (self-hosted via `@fontsource-variable`; a like-for-like dependency swap) on a fixed scale of 12 / 13 / 14 / 16 / 20 / 24 px with weights 400 / 600 / 700 and tabular figures for numbers. Motion uses tokens (100 / 160 / 240 ms, exponential ease-out); controls get a press state (scale 0.97) and menus and dialogs a short entry; reduced motion keeps colour and opacity changes and drops transforms.
**Consequences:** components keep using tokens, so the swap lives mostly in `styles/`; screens adopt the type-scale utilities (`text-label` … `text-display`) slice by slice through UX2–UX7. A light rail remains a token change if the product owner prefers it after UX2.
