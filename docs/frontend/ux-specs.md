# UX Specifications

Screen-by-screen behavior. Visual rules are in `design-system.md`. Each phase file references the sections it implements.

## 1. Shell

```
┌ Sidebar (248) ┬ TopBar (52): breadcrumb · search (⌘K) · ✦ Ask Mo · 🔔 · avatar ───────────┐
│ ◉ Momentum    │                                                                       │
│ [+ Create ▾]  │   <Outlet/>                                          │ Task pane │ Ask Mo │
│ Home          │                                                      │ (560)     │ (440)  │
│ My Tasks      │                                                      │           │        │
│ Inbox  (3)    │                                                      │           │        │
│ ✦ Ask Mo      │                                                      │           │        │
│ Agents        │                                                      │           │        │
│ Goals / Portfolios / Dashboards / Workload (Phase 6)                  │           │        │
│ ── Favorites  │                                                      │           │        │
│ ── Teams ▾    │ (team → projects list, colored dots)                 │           │        │
│ user block    │                                                      │           │        │
└───────────────┴──────────────────────────────────────────────────────┴───────────┴────────┘
```

- **Sidebar:** collapsible (`⌘\`). Sections: primary nav, Favorites (drag to reorder), Teams (expandable, projects under each, "+ New project"). Bottom user block: avatar, name, status, menu (profile, settings, theme, sign out).
- **+ Create menu:** Task (`Tab+Q` / `Q`), Project, Message to Mo, Import.
- **TopBar:** breadcrumb (Team › Project › View), search field opening the command palette, `✦ Ask Mo` (toggles the right panel, `⌘J`), notifications bell (count of unread inbox), avatar.
- **Task pane and Ask Mo** can be open together. When the viewport is < 1400 px, opening one collapses the other to a tab.

## 2. Home (`/`)

- Greeting as the page title ("Good morning, Ravi", Inter 20/600) + date + Mo one-liner (amber, Phase 3+): "You have 3 tasks due today; the Website Revamp launch is at risk."
- Cards: **My priorities** (next 5 tasks by due and priority), **Recent projects** (6 tiles), **Waiting on others** (tasks I created or follow that are assigned to others and overdue), **Agent activity** (Phase 5).
- Empty state for new users: "Create your first project" / "Import from Asana".

## 3. My Tasks (`/my-tasks`)

- A list view of tasks assigned to me across projects. Default sections: **Recently assigned**, **Today**, **This week**, **Later**. Auto-bucketing by due date moves tasks between Today, This week, and Later daily unless the user placed them manually (pinned).
- Columns: task, project chips, due, (fields: priority).
- Toolbar: filter (incomplete / completed / all), sort, `✦ Plan my day` (Phase 3).
- Same keyboard behaviors as the project list.

## 4. Project

### 4.1 Header
Project color chip + name (inline editable) + status dot + star + members avatar stack + Share + ⋯ (settings, save as template, archive, delete). Below: view tabs `Overview · List · Board · Timeline · Calendar · Dashboard` (Phase-gated), right side: `Filter · Sort · Group · Fields · ✦`.

### 4.2 List view (the most important screen)
- Sections with collapsible headers (name inline editable, ⋯ menu: rename, add section below, delete, move).
- Rows: `CompleteCheck` · title · subtask count ↳n · comment count 💬n · assignee avatar · due · custom fields · hover actions (open, more).
- **Add task:** "+ Add task" at the bottom of each section; `Enter` on a focused row creates a new row below; paste of multiple lines creates multiple tasks (with confirmation if > 5).
- **Inline editing:** click a cell to edit. `Tab` moves to the next cell. `Esc` cancels. `Enter` commits.
- **Selection:** click row → focus; `Shift+Click` range; `⌘/Ctrl+Click` toggle; `⌘A` in section. The bulk bar appears: assign, due, move, add to project, complete, delete, `✦ Ask Mo about selection`.
- **Drag and drop:** rows within/between sections; multi-select drag; drop indicator line; auto-scroll.
- **Subtasks:** expand arrow shows subtasks indented under the parent (read/edit inline). `Tab` on a new row indents to a subtask of the previous row; `Shift+Tab` outdents.
- **Filters/sort/group** persist in the URL and per-user prefs.
- **Completed tasks:** hidden by default; "Show completed" toggle loads them paged.

### 4.3 Board view (Phase 2)
Columns = sections; cards show title, assignee, due, cover color strip (project or field), subtask progress, comment count. Drag cards between columns; drag columns to reorder. "+ Add section" column at the end.

### 4.4 Calendar view (Phase 2)
Month (default) / week. Tasks on due date; multi-day bars when start and due are both set. Drag to reschedule; drag bar edges to change start/due. Click empty day → quick add with that date. "No date" tray on the side.

### 4.5 Timeline (Phase 6)
Rows = tasks grouped by section. Bars start→due; milestones as diamonds; dependency arrows; today line; zoom (week/month/quarter); drag/resize; shows the P50/P80 forecast marker for the project end (Phase 6).

### 4.6 Overview (Phase 6; lite version in Phase 3)
Brief (rich text), members and roles, key milestones, latest status update (+ history), `✦ Draft status update` button.

## 5. Task pane (`?task=<id>`)

```
[✓ Mark complete]  [👍] [📎] [↳] [🔗] [⋯]                         [⤢ full] [✕]
T-142 · Website Revamp › In progress
Title (large, inline editable)
Assignee   [avatar Ravi ▾]             Due date  [Fri, Sep 26 ▾]
Projects   [● Website Revamp › In progress] [+ Add to project]
Dependencies (P2)  Blocked by T-120 · Blocking T-150
Fields (P2)  Priority [High] · Effort [3h] …
Description  (Tiptap editor, placeholder "Add details…")
✦ Actions (P3): Summarize · Break into subtasks · Draft reply · Ask about this task
Subtasks  (list with add row)
Attachments (P2)
──────────────── Activity / Comments ────────────────
[filter: All · Comments · Activity]
  Ana created this task · 2d
  Ravi: "Can we reuse the old pricing table?" · 1d
  ✦ Mo summarized this thread · 3h  (amber callout)
[ Comment box (Tiptap, @mentions) ]  Collaborators: avatars + Follow/Unfollow
```

- Opens over any screen and updates the URL. `Esc` closes. `J`/`K` (or ↑/↓ in the list) moves to next/previous while the pane stays open.
- Full-page mode at `/task/:id`.

## 6. Inbox (`/inbox`)

- Tabs: **Activity** (default), **Archive**. Filters: mentions, assigned to me, all.
- Items grouped by task: "Ana commented on *Draft pricing copy*" + snippet + time. Click opens the task pane. `E` archives, `U` marks unread.
- `✦ Catch me up` (Phase 3): an amber callout summarizing unread items, grouped by project, with links.

## 7. Command palette (`⌘K`)

- Empty state: recent items + actions ("Create task", "Go to My Tasks", "Toggle theme").
- Typing searches tasks, projects, and people (fuzzy, trigram) and filters actions.
- **Natural language (Phase 3):** if the input looks like an instruction ("assign all overdue design tasks to Ana"), the top result is `✦ Ask Mo to do this` → the Mo panel shows a `PreviewCard` with the proposed changes → Apply / Edit / Cancel.
- Quick-add syntax (Phase 3, parsed locally first): `Review deck @ana tomorrow #marketing !high`. **As built (S3.2.1, in the quick-add dialog):** `@first`, `@"Full Name"`, `@first.last`, `@me`; `#project` (normalized prefix of an editable project); `!urgent|!high|!medium|!low`, `!p1`–`!p4`, `!!` high, `!!!` urgent; natural-language dates (the date picker's chrono setup); `every day|weekday|week|month|year|<weekday>[, and <weekday>]`, `every other …`, `every N weeks`, or a trailing `daily|weekly|monthly` (not as the first word). Recognized tokens leave the name ("Creates “Review deck”"), set the pickers, and show priority/repeat chips with ×; a hand-picked value always wins; ambiguous or unknown `@`/`#` show "Couldn't match …" (never guessed). When the rest still reads like details ("for Ana by end of next week"), an amber **✦ Let Mo fill in the details** button (only if AI is enabled) calls `POST /ai/quick-add`; Mo's reading is marked with the AI badge and nothing is created until the user adds the task.

## 8. Ask Mo panel (`⌘J`) and page (`/ask`)

- Context chip at the top: "Context: Website Revamp" (auto from current screen; removable).
- Streaming answers with citations as chips linking to tasks and projects.
- Tool activity is shown compactly ("Searched 3 projects · Read 12 tasks").
- Proposed changes appear as `PreviewCard` inside the conversation.
- Conversation history list (page view). Feedback 👍/👎 on each answer.
- Suggested prompts vary by context ("What's blocking this project?", "Summarize this week", "Plan my day").

## 9. Agents (Phase 5)

- `/agents`: gallery (starter agents + custom) with enable toggles, autonomy badge, last run, monthly cost.
- Agent detail: charter (instructions), triggers, tools, scope, autonomy, budget, test run button, run history.
- Run detail: timeline of steps (tool calls, results digest), proposals with Apply/Reject, cost, errors.
- Agents appear as members with a ✦ amber avatar ring; assigning a task to an agent shows "Mo agent will start within a minute".

## 10. Settings and admin

- Profile (name, avatar, timezone, theme), notifications (per kind: in-app / Slack / email / off; digest time), API tokens (create/revoke; shown once).
- Admin: members (invite, role, disable), teams, AI (enable, model aliases (read-only view), budgets, workspace memory, auto-apply policy), agents policy, integrations (Slack, calendar), background jobs, import.

## 11. States checklist (every screen)

| State | Required behavior |
|---|---|
| Loading | Skeleton matching final layout |
| Empty | `EmptyState` with a primary action (and ✦ AI option where relevant) |
| Error | `ErrorState` with retry + request id; the rest of the shell still works |
| No permission | "You don't have access to this project" + request-access hint (who to ask) |
| Offline / WS disconnected | Thin banner "Reconnecting…"; edits queue optimistically; failures roll back with toast |
| AI unavailable | AI buttons disabled with tooltip "Mo is unavailable right now"; core app unaffected |

## 12. Keyboard map (defaults; user-customizable later)

| Keys | Action |
|---|---|
| `⌘K` / `Ctrl+K` | Command palette |
| `⌘J` | Toggle Ask Mo |
| `Q` (or `Tab`+`Q`) | Quick add task |
| `Enter` | New task below (list) / commit edit |
| `Tab` / `Shift+Tab` | Indent/outdent (new row) · next/prev cell (editing) |
| `⌘Enter` | Complete / uncomplete focused task |
| `Space` | Open/close task pane for focused row |
| `↑/↓` or `J/K` | Move focus |
| `Shift+↑/↓` | Extend selection |
| `⌘↑/⌘↓` | Move task up/down |
| `A` | Assign focused task (picker) |
| `M` | Assign to me |
| `D` | Set due date (picker with NL input) |
| `S` | Add subtask |
| `C` | Focus comment box (pane) |
| `E` | Archive (inbox) |
| `⌘Z` | Undo last action |
| `?` | Shortcut sheet |
| `G` then `H`/`M`/`I`/`A` | Go to Home / My Tasks / Inbox / Ask Mo |
| `Esc` | Close pane/popover, cancel edit |
