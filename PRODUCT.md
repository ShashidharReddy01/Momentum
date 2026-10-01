# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
A small team (10–15 people) running their day-to-day work in Momentum instead of Asana: leads who plan projects, check workload and dashboards, and post status; contributors who live in My Tasks, the project list and the task pane. Mostly on **Windows laptops with display scaling at 125% or 150%** at 100% browser zoom, which leaves an effective window of about 1280–1536 × 600–730 CSS pixels (product owner, 2026-10-01). Agents ("Teammate", "Sorter", …) also act inside the product, and people review what they did.

## Product Purpose
An AI-native work manager: tasks, projects (list, board, calendar, timeline, overview, dashboard), portfolios, goals, workload, inbox, rules and forms, with an assistant (Mo) and AI teammates that propose changes people preview, apply and undo. Success is a team that plans and tracks all its work here, reads the state of a project at a glance, and trusts every number and every AI action.

## Positioning
Easier to read than Asana and honest by construction: every number is computed as the viewer and opens the tasks behind it; forecasts are ranges, not guesses; AI work is always marked, previewed and undoable, and code (not the model) decides what is counted or moved.

## Operating Context
All-day use at a desk on a laptop, often next to email and chat; heavy keyboard use (⌘K palette, Q quick add, J/K, ←/→ on the timeline, ⌘Z undo); realtime updates from teammates; quick status checks between meetings. Embedded use: Momentum can be mounted inside a host app (styles scoped to `.momentum-root`).

## Capabilities and Constraints
- React SPA (Vite, Tailwind v4, Radix primitives, TanStack Query), FastAPI backend; the frontend reads only the generated OpenAPI types.
- Design tokens live in `apps/web/src/momentum/styles/tokens.css` and are scoped to `.momentum-root` (no global style leakage for embedding); raw colour literals in components are forbidden by ESLint.
- Two themes, light and dark, switchable per user. Dark ("Graphite" with a lime accent) is approved by the product owner and may be refined; **light is to be completely redesigned** (Phase 6.5).
- Amber is reserved for AI-authored content and AI actions; purple marks mock data in development only.
- Must work from a 390 px phone up to 1920 px, with the scaled-laptop window as the primary target.
- Performance budgets: initial JS ≤ 300 KB gzip for the shell + list; heavy views (timeline, dashboards, charts, editor) are lazy.

## Brand Commitments
- Name **Momentum**; the "M" brand mark; the assistant is **Mo**, marked with the amber ✦.
- Dark theme: Graphite surfaces with the lime accent (keep).
- Benchmarks the product owner set as the craft bar: **Linear** (fast, crisp, keyboard-first, quiet chrome) and **Height / Things 3** (polished micro-interactions, delightful details).

## Evidence on Hand
Synthetic demo data only (`momentum seed`, `seed --history`): users Ravi, Ana, Priya, Mei and others; projects Website Revamp, Mobile App v2, Q4 Launch Campaign, Vendor Onboarding, and the Delivery history. No real customer data, testimonials or metrics may be shown or invented.

## Product Principles
- The task comes first: chrome recedes, content and state lead.
- Every number is honest and clickable; nothing is invented to fill a screen.
- AI is visible, reversible and never the boundary of trust.
- Keyboard and pointer are equals; every action gives immediate, legible feedback.
- One system everywhere: the same component behaves the same on every screen.

## Accessibility & Inclusion
WCAG 2.2 AA: text contrast ≥ 4.5:1, visible focus on every control, full keyboard operation, `prefers-reduced-motion` respected with an intentional alternative, and nothing conveyed by colour alone.
