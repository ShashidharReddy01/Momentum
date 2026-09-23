# Phase 1: Core Tasks MVP

**Goal:** run a real project end to end in the list view with the task pane, comments, activity, undo, and My Tasks. Milestone **M1 "Dogfood"**.

**Exit criteria**
- [ ] E2E J1 and J3 pass; J2 passes except inbox delivery (Phase 2)
- [ ] 2,000-task project scrolls smoothly; inline edits feel instant
- [ ] Permission matrix tests cover teams/projects/tasks
- [ ] Retro written in STATUS

---

## E1.1 Teams and projects

### S1.1.1: Teams
**Backend:** migration `teams`, `team_members`; services `create_team`, `update_team`, `delete_team` (soft), `add_team_member`, `remove_team_member`, `list_my_teams`; events `team.*` (add to catalog); activity + undo for update/delete. API `GET/POST /teams`, `GET/PATCH/DELETE /teams/{id}`, `POST/DELETE /teams/{id}/members`.
**Frontend:** sidebar "Teams" section lists my teams (expandable); "New team" dialog; team page `/teams/:id` (members list, projects list placeholder).
**AC**
- [ ] Any member can create a team and becomes its lead; admins see all teams
- [ ] Removing yourself as the last lead is blocked with a clear error
**Tests:** service + API permission matrix; sidebar render with MSW.
**Size:** M

### S1.1.2: Projects
**Backend:** migration `projects`, `project_members`, `favorites`; services `create_project` (creates a default "To do" section), `update_project`, `archive_project`, `delete_project`, `restore_project`, `list_team_projects`, member management, favorites; `permissions` project rules (auth doc §5, §6 incl. team default editor). API per api-conventions.
**Frontend:** "New project" dialog (name, team, privacy, color); sidebar projects under teams with color dots; project header (name inline edit, color, star, members stack, ⋯ menu: rename, archive, delete); Favorites section with drag reorder.
**AC**
- [ ] Private projects are invisible to non-members (404 on direct URL)
- [ ] Archive hides from the sidebar but is reachable via team page "Archived"
- [ ] Undo works for rename/archive/delete
**Tests:** visibility matrix (admin/member/non-member/private), undo tests, UI dialog tests.
**Size:** M

### S1.1.3: Project members and roles
**Build:** Share dialog: add people (combobox), set role (admin/editor/commenter/viewer), remove; enforcement in services (commenter can't edit, viewer can't comment).
**AC:** role changes take effect immediately (next request); the UI hides disallowed actions and the API still enforces them.
**Tests:** role matrix API tests; UI hides edit affordances for viewers.
**Size:** S

---

## E1.2 Sections and tasks (list view)

### S1.2.1: Sections
**Backend:** migration `sections`; `core/ordering.py` (fractional keys: `key_between(a, b)`, rebalance when keys exceed 32 chars); services create/rename/move/delete (delete requires moving tasks or deleting them. The API takes `{tasks: "move_to" | "delete", target_section_id}`).
**Frontend:** list view renders sections with collapsible headers, inline rename, ⋯ menu, "+ Add section", drag sections.
**AC:** order persists; concurrent inserts between the same neighbors produce distinct keys.
**Tests:** ordering unit tests (property-based with hypothesis), section service tests.
**Size:** M

### S1.2.2: Tasks: create, edit title, complete
**Backend:** migration `tasks`, `task_projects`, `followers`; `number` allocation (`UPDATE workspaces SET task_seq = task_seq + 1 RETURNING task_seq` in the same transaction); services `create_task(project_id, section_id, after_id?)`, `update_task` (title), `complete_task`/`uncomplete_task`, `delete_task`/`restore_task`, `list_project_tasks` (incomplete, all sections, ordered; completed paged). Creator and assignee auto-follow. `search_tsv` generated column.
**Frontend:** `features/tasks`: `TaskListView` (TanStack Virtual, grouped by section), `TaskRow` (CompleteCheck, InlineText title, counts), "+ Add task" per section, `Enter` creates a new row below and focuses it, paste multiple lines = multiple tasks (confirm if > 5), completion animation + "Show completed" toggle, optimistic mutations with Undo toasts.
**AC**
- [ ] Creating 10 tasks rapidly via Enter keeps order and focus
- [ ] Completing and undoing restores exact position
- [ ] Task keys `T-n` are unique and sequential per workspace
**Tests:** number allocation under concurrency (asyncio gather), ordering on create-after, list query count ≤ 4, UI keyboard tests.
**Size:** L

### S1.2.3: Assignee and dates
**Backend:** `update_task` supports `assignee_id` (must be a workspace member; agents allowed later), `start_on`, `due_on`, `due_at`; validation start ≤ due; `task.assigned` event.
**Frontend:** `AssigneePicker` (combobox, "Assign to me"), `DatePicker` with NL input (`chrono-node`, user timezone) + calendar + quick picks (Today, Tomorrow, Next week, No date); DueText coloring rules; shortcuts `A`, `M`, `D`.
**AC:** "next fri", "in 3 days", "sept 30", "tomorrow 5pm" parse correctly for the user's timezone; overdue rows show crit text.
**Tests:** date parsing table tests with frozen time; picker keyboard tests.
**Size:** M

### S1.2.4: Drag and drop, multi-select, bulk actions
**Backend:** `move_task(project_id, section_id, before_id|after_id)`, `bulk_update_tasks(ids, patch)`, `bulk_move`, `bulk_complete`, `bulk_delete` (one activity batch → batch undo).
**Frontend:** dnd-kit sortable across sections (multi-drag), auto-scroll, drop indicator; selection store (click, shift-range, cmd-toggle, ⌘A); bulk bar (assign, due, move to section, complete, delete); `⌘↑/⌘↓` move.
**AC:** moving 20 selected tasks is one undoable action; order persists after reload.
**Tests:** move ordering tests; batch undo; UI selection logic unit tests.
**Size:** L

### S1.2.5: Filter, sort, group; persisted view prefs
**Backend:** `list_project_tasks` supports filters (assignee, due range, completed state) and sort (manual default, due, assignee, created); user view prefs endpoint `PUT /me/prefs/views/{project_id}`.
**Frontend:** toolbar Filter/Sort/Group popovers; URL search params; group by section (default)/assignee/due bucket. Drag disabled when sorted by non-manual (with hint).
**AC:** a shared URL reproduces the same view; prefs restore on revisit.
**Size:** M

### S1.2.6: Performance pass for the list
**Build:** 2,000-task seed project; memoized rows; selection selectors by id; measure and document.
**AC:** scroll at 60fps on a mid laptop; edit feedback < 50 ms; initial render < 1s after data.
**Size:** S

---

## E1.3 Task pane

### S1.3.1: Pane shell and core fields
**Frontend:** `TaskPaneHost` driven by the `?task=` URL param; header actions (complete, copy link, more: delete, duplicate later); title (large inline), assignee, due/start, projects row (read-only in P1), description (Tiptap: headings, lists, checklists, links, code; paste markdown), autosave with debounce + `If-Match` version; draft kept in localStorage; `J/K` navigation keeps the pane open; `Esc` closes; full-page `/task/:id`.
**Backend:** `GET /tasks/{id}?include=…`; description updates with version check (409 → UI shows "Updated elsewhere, reload/merge" with both versions).
**AC:** description never loses typed text on conflict or session expiry.
**Tests:** conflict flow; draft restore; keyboard navigation.
**Size:** L

### S1.3.2: Subtasks
**Backend:** `create_subtask(parent_id)`, reorder via `parent_position`, subtasks inherit visibility; list endpoint includes `subtask_count`/`completed_subtask_count`.
**Frontend:** subtasks section in the pane (add row, reorder, complete, assign/date inline); open a subtask in the pane with breadcrumb back to the parent; list rows show ↳ count and expand arrow to show subtasks inline; `Tab` on a new row makes a subtask, `Shift+Tab` outdents (converts back to a top-level task in the same section).
**AC:** a subtask of a task in a private project is invisible to non-members even via direct link.
**Size:** M

### S1.3.3: Followers
**Build:** follow/unfollow, collaborator avatars in the pane footer, auto-follow on assign/comment/mention.
**Size:** S

---

## E1.4 Comments, activity, undo

### S1.4.1: Comments with mentions and reactions
**Backend:** migration `comments`, `mentions`, `reactions`; services create/edit (author only, 15 min edit window not enforced, shows "edited")/delete (soft); parse mentions from Tiptap JSON (`mention` nodes for user/task/project) → `mentions` rows; reactions add/remove.
**Frontend:** comment composer (Tiptap mini: bold, italic, lists, links, @mention popup searching people/tasks/projects), `⌘Enter` submits, comment list with edit/delete/react, mention chips linking to people/tasks.
**AC:** @mentioning a person makes them a follower; mentioning a task shows a backlink on that task (Phase 2 display).
**Tests:** mention parsing unit tests; permission (commenter can comment; viewer can't).
**Size:** M

### S1.4.2: Activity feed
**Backend:** `list_activity(entity)` merged with comments into a feed (typed items); human-readable rendering data (field, old, new, actor).
**Frontend:** pane feed with filter (All / Comments / Activity); collapsed runs of minor changes ("Ana changed 3 fields").
**Size:** M

### S1.4.3: Generic undo
**Backend:** `POST /undo {activity_id|batch_id}`; undo registry (`UndoOp` kinds → handler functions); rules: only the actor (or admin) can undo, within 24h, and only if the entity hasn't changed since (version check), else 409 with an explanation.
**Frontend:** Undo in toasts; `⌘Z` global handler (not in text inputs) undoes the last action in this session.
**AC:** undo works for every Phase 1 mutation type (test table).
**Size:** M

---

## E1.5 My Tasks and Home

### S1.5.1: My Tasks
**Backend:** `list_my_tasks` across visible projects; personal buckets: stored per user (table `my_task_placements`, see data-model.md); auto-bucketing job at local midnight moves unpinned tasks by due date.
**Frontend:** My Tasks page per ux-specs §3 with the same row component, drag between buckets (pins), project chips.
**AC:** a task assigned to me appears in "Recently assigned" immediately (on next fetch; realtime in P2).
**Size:** M

### S1.5.2: Home
**Frontend:** greeting (page title), date, "My priorities" (top 5), "Recent projects" (from activity), "Waiting on others", empty states for new users.
**Backend:** `GET /home` aggregate endpoint (single round trip).
**Size:** S

---

## Phase 1 notes
- AI tools for these mutations are registered in Phase 3 (S3.1.2 sweeps all services).
- Realtime (other users' changes) arrives in Phase 2. Until then, TanStack Query refetches on window focus.
