# Phase 2: Daily-Use Parity

**Goal:** everything the team uses Asana for day to day, plus live updates and importers. Milestone **M2 "Parity"**.

**Exit criteria:** J2, J4, J5, J6 pass; Asana import of a recorded fixture workspace matches expected counts; notifications feel right (not noisy) in a one-week self-dogfood.

---

## E2.1 Realtime (first, because everything after benefits)

### S2.1.1: WS hub and outbox dispatcher
**Scope:** `realtime/` hub (per-process), `LISTEN momentum_events`, subscribe/unsubscribe with permission checks, ping/pong, replay since id, resync; outbox dispatcher job; `consumer_offsets` table.
**AC:** two browsers see task title/section/complete changes within 1s; denied channel subscription rejected; reconnect replays missed events.
**Tests:** WS tests (permissions, replay, resync), dispatcher idempotency.
**Size:** L

### S2.1.2: Frontend realtime client
**Scope:** `lib/realtime` client (backoff, replay, re-subscribe), `useChannel`, `handlers.ts` for all Phase 1 events, reconciliation with optimistic updates, "Reconnecting…" banner.
**AC:** no flicker or double-apply for the actor's own changes; list order stays consistent under concurrent moves.
**Size:** M

## E2.2 Views

### S2.2.1: Board view
**Scope:** columns = sections, card component (title, assignee, due, subtask progress, comment count, color strip), drag cards/columns (dnd-kit), add card/section, card click → pane.
**AC:** keyboard: arrow navigation between cards, `Enter` opens, `⌘←/→` moves card between columns.
**Size:** L

### S2.2.2: Calendar view
**Scope:** month/week grid (custom or FullCalendar, decided at kickoff), tasks by due, multi-day bars, drag to reschedule/resize, click day → quick add, "No date" tray.
**AC:** timezone-correct for users in different zones (test with two zones).
**Size:** M

### S2.2.3: View switcher and defaults
**Scope:** tabs from ux-specs §4.1, per-project default view (project admin), per-user last view remembered.
**Size:** S

## E2.3 Custom fields and tags

### S2.3.1: Field definitions and library
**Scope:** migration `field_defs`, `project_fields`, `field_values`; field types per data model; create/edit/archive options; workspace library.
**Size:** M

### S2.3.2: Fields in views
**Scope:** fields as list columns (resize, reorder, hide), inline editors per type (`FieldValueEditor`), pane "Fields" section, filter/sort/group by field (incl. group by single-select on board: board "group by field" option).
**AC:** 10 fields × 2,000 tasks keeps list performance within budget.
**Size:** L

### S2.3.3: Tags
**Scope:** tags CRUD, TagPicker, tag chips (text-colored), filter by tag, tag page (tasks across projects).
**Size:** S

## E2.4 Multi-homing, dependencies, milestones

### S2.4.1: Multi-homing
**Scope:** add/remove task to/from projects (each with its own section/position), pane "Projects" row editable, list shows other-project chips.
**AC:** a task in a private and a public project is visible to public-project viewers; private-project context isn't leaked (chip hidden for non-members).
**Size:** M

### S2.4.2: Dependencies
**Scope:** blocked by / blocking in the pane; cycle detection (recursive CTE); "waiting on" icon in rows; completing a task with incomplete blockers asks for confirmation; event `task.dependency_*`.
**Size:** M

### S2.4.3: Milestones
**Scope:** task type milestone (diamond check icon), convert task ↔ milestone.
**Size:** S

## E2.5 Notifications and inbox

### S2.5.1: Notification generation
**Scope:** migration `notifications`; consumer maps events → notifications per the rules table (assigned to you, mentioned, comment on followed task, completed task you created, due soon (job at 09:00 local), overdue (job)); coalescing (same task within 10 min merges); user prefs per kind.
**AC:** you don't get notified for your own actions; no duplicates on dispatcher retry.
**Size:** M

### S2.5.2: Inbox UI
**Scope:** `/inbox` per ux-specs §6, bell count (realtime via `user:<id>` channel), archive/unread, keyboard `E`/`U`, grouping by task.
**Size:** M

### S2.5.3: Notification preferences
**Scope:** settings page (per kind: in-app / email-later / Slack-later / off), digest time preference (used by Pulse agent in P5).
**Size:** S

## E2.6 Attachments and search

### S2.6.1: Attachments (local storage backend)
**Scope:** `StorageBackend` interface + `local`; upload endpoint (streaming, size limit, MIME sniffing, sha256), download with auth, image/PDF preview, attach via drag-drop/paste into the pane and comments; text extraction job (pdf via `pypdf`, docx via `python-docx`, plain text) → `text_extract`.
**AC:** files are not accessible without task visibility (direct URL test).
**Size:** M

### S2.6.2: Global search
**Scope:** `GET /search?q=` across tasks (tsvector + trigram), projects, people, comments; results page with filters (type, project, assignee, completed); `⌘K` quick results (top 8, grouped).
**AC:** p95 < 150 ms on the seed workspace; permission-filtered in SQL.
**Size:** M

## E2.7 Import and onboarding

### S2.7.1: Asana importer
**Spec:** `docs/integrations/asana-import.md` (object, field, and custom-field mapping, algorithm, validation).
**Scope:** `integrations/asana_import`: user supplies a PAT at import time (never stored), picks teams/projects; background job with progress events; maps users by email (unmatched → invite placeholders or map-to picker), teams, projects (privacy), sections, tasks (+subtasks, assignee, dates, completed, description (HTML → Tiptap)), custom fields (types mapped; enum options), tags, dependencies, comments (as imported comments authored by mapped users, with an "imported" marker), attachments (link-only by default; download optional); `external_links` store Asana gids for idempotent re-runs; rate-limit aware (Asana's ~1,500 req/min paid limit, with backoff on 429).
**AC:** re-running the import updates rather than duplicates; a recorded fixture of a sample Asana workspace (synthetic) imports with exact counts.
**Tests:** VCR-style recorded responses (synthetic data only); mapping unit tests.
**Size:** L

### S2.7.2: CSV import
**Scope:** upload CSV → column mapping UI → preview → import into a project (sections from a column optional).
**Size:** S

### S2.7.3: Onboarding
**Scope:** invite users (admin), first-run checklist on Home (create project / import / try ⌘K), shortcut sheet.
**Size:** S
