# Phase 1 Kickoff

**Date:** 2026-09-23 · **Model:** Opus 5.5 (whole phase) · **Phase goal:** run a real project end to end in the list view, with the task pane, comments, activity, undo, and My Tasks (M1 "Dogfood").

## 1. State check (code vs. phase file)

| Area | Reality after Phase 0 | Consequence |
|---|---|---|
| Permissions | `core/permissions.py` handles workspace-level actions only. `core` may not import `domain` (import-linter). | Project/team/task access needs DB lookups, so it lives in a new **`momentum/domain/access.py`** (role resolution + SQL visibility clauses). `core/permissions.py` stays for workspace-level rules. |
| Undo | `activity.undo_payload` exists; no executor | Build a small **undo registry** in `core/undo.py` (handlers registered by domain modules) plus `POST /api/v1/undo` in S1.1.1, because S1.1.x ACs already need undo. S1.4.3 then generalizes and completes it (⌘Z, batch undo UI, coverage table). |
| Response shapes | `/me` returns a plain object | From Phase 1, lists return `{data, meta}` and mutations return `{data, meta: {activity_id, batch_id, version}}` per api-conventions. `/me` stays as is (bootstrap). |
| People lookup | None | Add `GET /api/v1/users` (workspace members, search) in S1.1.1, needed by every picker. |
| Frontend deps | Not yet installed | Added in the slice that first needs them: `@tanstack/react-virtual` (S1.2.2), `chrono-node` (S1.2.3), `@dnd-kit/*` (S1.2.4), `@tiptap/*` (S1.3.1). |
| Seed data | 12 users only | Each slice extends `momentum seed` with synthetic data for what it adds (teams → projects → sections → tasks → comments), so the app is always explorable. |
| Dev env (build container) | Background processes (Postgres, API) are stopped between sessions | Restart at session start; documented in the handoff notes. |

## 2. Refinements

| Slice | Change | Reason |
|---|---|---|
| S1.1.1 | Also delivers: `core/undo.py` registry, `POST /undo`, `GET /users`, generic `ListOut`/`MutationOut` schemas, `PeoplePicker`, `Popover` primitive, undo toast helper | Foundations every later slice uses |
| S1.4.3 | Scope becomes "generalize and complete undo" (⌘Z, batch undo, coverage table across all Phase 1 mutations) | Undo basics land in S1.1.1 |
| All | Event channels: `team:<id>`, `project:<id>`, `task:<id>`, `user:<id>` | Consistent realtime subscriptions in Phase 2 |

## 3. Risks

| Risk | Mitigation |
|---|---|
| List view complexity (virtualization + DnD + inline edit + keyboard) | Build S1.2.2 without DnD first; add DnD in S1.2.4 with its own tests; measure in S1.2.6 |
| Permission rules scattered | Single module `domain/access.py`; a matrix test per role |
| Undo correctness | Version check before undo; tests per mutation type |

## 4. Exit criteria (confirmed)
As in `phase-1.md`: J1 and J3 pass; J2 passes except inbox delivery; a 2,000-task list is smooth; the permission matrix is covered; retro written.
