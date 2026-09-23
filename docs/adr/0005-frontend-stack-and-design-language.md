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
