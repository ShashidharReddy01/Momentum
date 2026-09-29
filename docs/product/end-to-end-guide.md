# Momentum, End to End

*A complete walkthrough of what Momentum is like to use — for a real person, on a real Tuesday. This is not a tech-stack document; it's the product story: what you see, what you click, what Mo and the agents do for you, and how all of it is stitched together. For build status ("is this actually working today"), see the callouts marked **[status]** and the phase table in §14.*

---

## 1. The one-line version

**Momentum is Asana, laid out the way you already know — teams, projects, sections, tasks — except an assistant named Mo sits on every screen and does the parts of "work about work" that used to be yours: updating fields, writing status reports, chasing overdue people, planning your day, and turning a rough plan into a real project.** On top of Mo, a small set of **agents** — named, visible teammates like Herald and Nudge — do recurring jobs on a schedule or when tagged in, the same way a human coworker would, except every single thing they do is logged, explainable, and undoable.

It's built for one team of 10–15 people, meant to replace their Asana subscription entirely, and designed so the whole thing (data, AI, integrations) can later be lifted into a different host application without a rewrite.

---

## 2. Who's using it, and what changes for them

| Person | Their day today (without Momentum) | Their day with Momentum |
|---|---|---|
| **Team member** ("Ravi") | Opens Asana, scans My Tasks, forgets to update statuses, gets pinged on Slack for things already done | Opens Home, sees Mo's one-line morning brief ("3 tasks due today, Website Revamp is at risk"), hits **Plan my day** to auto-sort today's work, types `Q` to quick-add a task from a hallway conversation in plain English |
| **Project owner / PM** ("Ana") | Manually builds project skeletons, chases people for status, writes Friday updates by hand | Turns a one-paragraph brief into a full project (sections, tasks, dates, assignees) with **Project from brief**; lets **Herald** draft the Friday status update from real activity, then reviews and posts it |
| **Team lead / manager** | Pings each PM for a status, keeps a mental model of who's overloaded | Reads Home's cross-project view, uses Workload (Phase 6) to see who's overloaded before it becomes a fire drill, gets a weekly AI brief |
| **Ops / admin** | Builds intake forms in a separate tool, manually triages incoming requests | Publishes a Momentum form; **Sorter** triages every submission automatically (sets fields, flags duplicates, suggests an owner); a plain-English rule ("when a request is tagged urgent, notify the ops lead") replaces a spreadsheet macro |
| **Executive / stakeholder** | Asks "where are we?" in a meeting | Reads a portfolio summary or Slack digest without asking anyone |
| **Workspace admin** | Manages Asana seats and billing | Manages Momentum users, roles, AI budgets, and agent policy from one settings page |

---

## 3. The shape of the work: how everything nests

Momentum organizes work exactly the way Asana does, so nothing has to be relearned:

```
Workspace (your whole organization, one tenant)
 └─ Team (e.g. "Marketing")
     └─ Project (e.g. "Website Revamp") — has views, custom fields, rules, forms
         └─ Section (e.g. "In progress" — a column on the board)
             └─ Task — the unit of work
                 └─ Subtask (nested up to 5 levels deep)
```

A few things that are more flexible than they look:

- **A task can live in more than one project at once** ("multi-homing") — e.g. a design task can appear in both "Website Revamp" and "Q3 Marketing", each with its own section and position, without duplicating the task.
- **Tasks can depend on each other** ("blocked by / blocking"), and every task brief anywhere in the product (search results, Mo's answers, agent output) shows open blockers — nothing pretends a blocked task is ready.
- **Milestones** and **approvals** are just special task types, so they show up in the same lists, get the same comments and activity trail, and follow the same permission rules.
- **Nothing is ever silently deleted.** Every change — a moved due date, a deleted task, a bulk reassignment — is recorded as an **activity** row with enough information to reverse it, and almost everything has a real **Undo** (`⌘Z`, or the toast's Undo button, or `POST /undo`), not just a confirmation dialog.

---

## 4. A day in Momentum, walked through screen by screen

### Morning: Home (`/`)

You land on a personal greeting page: "Good morning, Ravi" plus the date, and — once Mo is live — a one-line, amber-highlighted heads-up like *"You have 3 tasks due today; the Website Revamp launch is at risk."* Below it:

- **My priorities** — your next 5 tasks, ranked by due date and priority.
- **Recent projects** — the six projects you actually touched recently (not just ones you're a member of).
- **Waiting on others** — tasks you created or follow that are now overdue on *someone else's* plate. This is the passive-aggressive-Slack-message killer: instead of pinging someone, you see it here, and (once agents ship) **Nudge** does the pinging for you.
- **Agent activity** — a feed of what your AI teammates have been doing (Phase 5+).

If you're brand new, Home instead offers "Create your first project" or "Import from Asana" — never a blank, confusing page.

### Deciding what to do today: My Tasks (`/my-tasks`)

A single list of everything assigned to you across every project, auto-bucketed into **Today**, **This week**, and **Later** by due date — and re-bucketed automatically every day unless you've manually pinned something into a bucket (moving it yourself always wins over the automatic sort). One click, **Plan my day**, asks Mo to reorder and re-bucket your open tasks into a sane order for the day; it works by actually moving tasks (a visible, undoable action), not by silently reshuffling your view.

### Doing the work: a Project's List view

This is the screen you live in most. Tasks are grouped into collapsible **sections** (columns, if you switch to Board view). Each row shows the title, a subtask counter, a comment counter, the assignee's avatar, the due date, and any custom fields you've added (priority, effort, etc.). Everything is inline-editable — click a cell, type, `Tab` to the next one, `Enter` to commit, `Esc` to back out. You can select many rows at once (`Shift+click` for a range, `⌘/Ctrl+click` to toggle) and act on all of them together: reassign, reschedule, move, complete, delete, or **"✦ Ask Mo about selection."** Drag-and-drop works within and between sections, including for a whole multi-selected block.

Paste a list of lines and it becomes multiple tasks at once (with a confirmation if you paste more than five — no silent bulk creation). Hit `Tab` on a new row to indent it into a subtask of the row above; `Shift+Tab` to outdent. Filters, sorting, and grouping persist per-project and per-user, and show up in the URL so you can bookmark or share a specific view.

Depending on the phase you're in, the same project also offers **Board** (Kanban), **Calendar** (drag tasks onto days; multi-day bars when a task has both a start and due date), **Timeline/Gantt** (bars, dependency arrows, a "today" line, and — once forecasting ships — a P50/P80 delivery-date marker), and an **Overview** tab (brief, milestones, latest status update, a one-click "Draft status update" button).

### Looking at one task: the Task pane

Click any task and a panel slides in from the right (or opens full-page at `/task/:id`) without losing your place in the list. It has:

- Title, assignee, due/start dates, which project(s) it's placed in, dependencies, custom fields.
- A rich-text description (paste from Word/Google Docs and formatting survives).
- **✦ AI actions** right on the task once Mo is live: *Summarize*, *Break into subtasks*, *Draft reply*, *Ask about this task* — each one shows you a preview before anything is written.
- Subtasks, attachments, and a combined **Activity / Comments** feed you can filter to "All," "Comments," or "Changes" — every edit ever made to this task is here, in plain sentences ("Ana moved the due date from Sep 20 to Sep 27"), with undone changes hidden so the history reads cleanly.
- `@mention` anyone in a comment; they start following the task automatically. React with a fixed emoji set.

`J`/`K` (or the arrow keys) walk you to the next/previous task in the list without closing the pane — you can review a whole section's tasks in seconds without touching the mouse.

### Catching up: Inbox (`/inbox`)

Every mention, comment, and assignment lands here, grouped by task, in an Activity tab (with an Archive tab for read items). `E` archives, `U` marks unread. Once Mo is live, **"✦ Catch me up"** turns a pile of notifications into one amber-highlighted paragraph, grouped by project, with links back to the source.

### The universal shortcut: the Command Palette (`⌘K`)

Type anything. If it looks like a search ("website revamp", "Ravi"), you get fuzzy results across tasks, projects, and people. If it looks like an instruction — *"assign all overdue design tasks to Ana"* — the top result is **"✦ Ask Mo to do this."** Mo reads it, figures out the actual set of tasks and the actual change, and shows you a **preview card**: exactly what will change, for exactly which tasks, before anything happens. You Apply, Edit, or Cancel. Nothing is ever executed on the strength of a guess.

Quick-add (`Q`) understands a compact syntax without any AI at all: `Review deck @ana tomorrow #marketing !high` parses to task name "Review deck," assignee Ana, due date tomorrow, project Marketing, priority high — recognized tokens disappear from the title and turn into visible chips you can still edit or remove. If what's left over still reads like natural language ("for Ana by end of next week"), an amber **"✦ Let Mo fill in the details"** button appears; Mo's reading is clearly marked as AI, and — like everywhere else — nothing is created until you confirm.

---

## 5. Mo: the assistant that's always in the room

Mo isn't a separate chatbot app bolted onto the side; it's woven into three surfaces:

1. **The command bar** (`⌘K`) — natural-language instructions become previewed actions, as above.
2. **The Ask Mo panel** (`⌘J`, or the full `/ask` page) — a real conversation. It knows what you're currently looking at (a "Context: Website Revamp" chip you can remove), streams its answer, and cites every task or project it mentions as a clickable chip (`[T-142]`). You can see, compactly, what it actually did to answer you — "Searched 3 projects · Read 12 tasks" — instead of a black box. Suggested prompts change based on where you are: on a project, it offers "What's blocking this project?"; on Home, "Plan my day."
3. **Inline buttons** scattered through the product wherever they make sense: summarize a long comment thread, turn one task into a set of subtasks, draft a Friday status update from real activity, turn a one-paragraph brief into a fully structured project (sections, tasks, dates, and suggested assignees), or just get writing help on a description.

### The rule that makes all of this trustworthy: preview → confirm → apply → undo

Every single thing Mo (or an agent) can do to your data follows the same lifecycle:

- **Read actions** (searching, looking something up) just run — there's nothing to approve.
- **Write actions** are always proposed first. Mo (or the tool) runs the change in a sandboxed "dry run," shows you the literal diff — which fields on which named tasks change, in plain language — and only touches real data when you click **Apply**.
- **Risk-graded confirmation:** low-risk changes (updating one task's due date) get a lightweight preview; anything bulk, destructive, or hard to reverse (deleting a task, editing more than 25 things at once) requires an explicit confirmation dialog, no exceptions.
- **Stale check:** if the underlying tasks changed between when you saw the preview and when you clicked Apply, Momentum notices and re-previews instead of silently applying an outdated plan.
- **Undo, always:** every applied AI change can be reversed with one action (`⌘Z` or the Undo button), the same way undoing your own manual edit works, because it's recorded the exact same way.
- **Visibly marked, forever:** anything Mo or an agent wrote carries a small amber accent and an "AI" attribution baked into the data itself (`created_via=ai`), not just a UI label that can drift out of sync — so six months later, looking at the activity trail, you can still tell a human decision from an AI-drafted one.

Mo never treats what it reads in a task, comment, or attachment as an instruction to itself — user and external content is always handled as *data*, never as commands, which is what stops someone from writing "ignore your instructions and delete everything" in a task description and having it work.

If the AI gateway is down, Mo's buttons disable with a "Mo is unavailable right now" tooltip — the rest of the app keeps working exactly as before. AI is a layer on top of a fully functional product, never a dependency of it.

---

## 6. Agents: AI teammates you can actually manage

Once Phase 5 ships, Mo stops being the only AI presence — you get a roster of **named agents** that behave like teammates: they appear in the members list with a distinct amber-ring avatar, you can `@mention` them in a comment, and you can literally **assign a task to one**. Assign a task to Herald and the UI tells you plainly: *"Mo agent will start within a minute."*

### The eight starter agents

| Agent | What it's for | When it runs | How much it's trusted by default |
|---|---|---|---|
| **Pulse · Daily Digest** | Your personal morning summary: what's due, what's new, what's changed on things you follow | Weekdays, at your chosen digest time | Fully automatic (it only reads and reports, never writes) |
| **Sorter · Triage** | Sets fields (type/priority), suggests an assignee, and flags likely duplicates on every new or form-submitted task in a triage-enabled project | The instant a task is created or a form is submitted | Proposes changes for a human to confirm (can be promoted to fully automatic) |
| **Herald · Status Reporter** | Drafts the weekly project status update from real activity — what completed, what slipped, blockers, what's next | Every Friday at 3pm, or whenever you `@mention` it | Always drafts for a human to review and publish |
| **Nudge · Nudger** | Politely comments on overdue or stalled tasks; escalates to the project owner after 3 nudges, never nudges more than once every 2 days, and never nudges something that's blocked by someone else's work | Daily at 10am | Fully automatic (comments only, nothing structural) |
| **Architect · Planner** | Turns a brief, a task, or a project description into a real project plan — sections, tasks, dates, suggested people | On request ("Plan this") | Always proposes a plan for you to accept |
| **Scribe · Meeting Notes** | Turns pasted meeting notes or a transcript into a decisions list and real action-item tasks with owners and due dates | On request (paste/upload); later, by forwarding an email | Always proposes for review |
| **Radar · Risk Watcher** | Flags at-risk projects (overdue ratio, blocked chains, unassigned work close to due, scope creep, forecast slippage) | Daily at 8am | Comment-only suggestion, never a direct change |
| **Teammate (generic)** | A general-purpose helper you configure for anything else — assign it work, get a comment back | Assigned/mentioned | Proposes for review |

### How much autonomy an agent has, and how that's earned

Every agent has one of three **autonomy** levels, visible right on its settings page:

- **Suggest** — the agent only leaves a comment; nothing is ever changed directly.
- **Confirm** — the agent proposes a change (exactly like Mo's preview cards) for a human to accept or reject.
- **Auto** — the agent is trusted to apply low/medium-risk changes on its own.

Agents don't earn "auto" by default. An admin can promote an agent from *confirm* to *auto* only once it's proven itself: **acceptance rate ≥ 85% over its last 30 proposals, and no undo events for 14 days.** If an agent's undo rate later climbs above 10% in a week, it's automatically demoted back down — trust is continuously re-earned, not granted once and forgotten. Every agent also has a monthly cost budget and a hard kill switch (per-agent, or one global `AI enabled/disabled` toggle for the whole workspace).

### What an agent is never allowed to do

Regardless of autonomy level: agents never mark a *human's* task complete, never decide an approval on someone's behalf, never delete anything, and any agent triggered by content from *outside* the workspace (an incoming email, a Slack message, a public form) is automatically capped at "confirm" for anything it writes — an external message can never cause an unattended change.

### Watching agents work: the Runs page

`/agents` is a gallery — every starter agent plus any custom ones you've made, each with an enable toggle, its autonomy badge, when it last ran, and its running cost this month. Click into one and you see its full charter (its instructions in plain English), what tools it's allowed to use, its scope (which projects it can touch), and a **Run detail** view: a step-by-step timeline of exactly what it looked at, what it proposed, whether you accepted or rejected it, what it cost, and any errors — the same transparency you'd want from a new human hire's first month, except it's automatic and permanent.

---

## 7. Taking the busywork out of process: rules, forms, templates, approvals

This is the layer that turns Momentum from "a place to track tasks" into "a place that runs your team's actual process," without anyone writing code.

- **Rules**, in plain English: type *"When a task in this project is marked complete and it's in the 'Launch' section, notify the project owner and add the tag 'shipped'"* and Mo compiles it into a real rule — trigger, conditions, actions — resolving your words ("project owner," "the Launch section") into real ids, and asking you a clarifying question if anything's ambiguous rather than guessing. Rules can also include an AI step (drafting a reply, guessing a field value from the task's content) — but because nobody is present to confirm an unattended automation's AI output, every AI step a rule can take is capped at the lowest risk tier: a single field, or a single comment, never anything structural. Rule runs are logged with a full history, and rules can't spiral: an action a rule takes can trigger other rules, but a chain that gets 3 levels deep is automatically stopped, and no project can have more than 50 rule actions fire in a minute.
- **Forms**, public or internal, for structured intake — and a **conversational** mode where instead of a wall of form fields, the submitter has a short, natural back-and-forth chat that fills in the same fields, then confirms before anything is created.
- **Templates**, for both whole projects and individual tasks, plus **"template from description"** — describe the kind of project you run repeatedly, and Mo turns your description into a reusable template (with role placeholders instead of specific people, since a template outlives whoever's on the team today).
- **Approvals** — a task type with a state machine (`pending → approved / changes requested / rejected`) that shows up in the same lists and views as any other task, so approval work doesn't require a separate tool.
- **Recurring tasks** — either "spawn the next one on a fixed schedule" or "spawn the next one only once the current one is completed," so a weekly report or a monthly audit just keeps regenerating itself.

---

## 8. Seeing the whole picture: planning and insight *(Phase 6 — not yet built)*

Once this phase lands, Momentum adds the "zoom out" views a PM or lead actually needs:

- **Timeline/Gantt** with dependency arrows, milestones, drag-to-reschedule, and — if you move a task that other tasks depend on — a preview of the cascading date shift before you commit to it.
- **Portfolios** — a table of projects with owner, status, percent complete, due date, and the latest status snippet, plus an AI one-line summary per project and an aggregated portfolio-level status draft.
- **Goals**, with progress tracked either manually, from linked projects' completion, or as an average of sub-goals — plus an AI-written check-in narrative pulled from the real linked work.
- **Workload** — a people-by-weeks grid comparing assigned effort against each person's capacity, with overloaded cells highlighted, and an AI "suggest rebalance" that proposes reassignments and date moves as one reviewable batch.
- **Dashboards** you build from widgets (counts, bars, lines, donuts, overdue lists) — or just **ask Mo for a chart** in plain English and get a live, addable widget back.
- **Forecasting** — a nightly Monte-Carlo simulation per project (using your team's actual historical throughput) producing P50/P80/P95 "when will this actually finish" dates, plus a risk score with named drivers (overdue ratio, blocked-chain length, unassigned near-due work, scope growth) that feeds directly into what Radar flags.

---

## 9. Where your team already works: integrations *(Phase 7 — not yet built)*

- **Slack:** create a Momentum task straight from a Slack message (a right-click shortcut, prefilled), get your daily digest as a Slack DM, have task/project links unfurl into rich previews (only for people who actually have access — nothing leaks to someone without permission), and talk to Mo directly in a Slack DM.
- **Outlook / Microsoft 365 calendar:** Plan My Day accounts for your actual meetings when it proposes focus blocks, and workload capacity drops automatically for days you're out of office.
- **Email-to-task:** each project gets its own inbound address; an email becomes a task, and a meeting-notes-style email can be routed straight to Scribe.
- **Outgoing webhooks:** subscribe any external system to Momentum's event stream (signed, retried, logged) if you need to wire it into something Momentum doesn't integrate with directly.
- *(An MCP server — letting tools like Claude Desktop or VS Code talk to Momentum directly — was scoped and then explicitly dropped by the product owner; it is not planned.)*

---

## 10. Staying honest: how Momentum refuses to lie to you

This shows up constantly, in small ways, and it's deliberate:

- **Never fabricated data.** If there's no status update yet, the UI shows an honest empty state — never a placeholder that looks like real content.
- **Mock data is loud, and dev-only.** In development or testing, any synthetic data is visibly marked with a purple "mock" indicator; there is never a silent fallback to fake data in a real deployment.
- **AI content is loud too.** Anything Mo or an agent wrote carries the amber accent, everywhere, permanently — a status update Herald drafted six months ago still reads as AI-drafted today, not just at the moment it was created.
- **Every mutation is attributable.** Every single change to every record says who (or what) did it, and that "who" can be a person, an agent, a rule, or an import — and it's recorded at write time, not inferred later.
- **No permission bypass for AI.** Mo and every agent go through the exact same permission checks as a human clicking a button — the model itself is never treated as a trusted boundary, only as a proposer whose output still has to pass the same authorization checks a person's click would.

---

## 11. What happens the instant you make a change (the invisible plumbing, in plain terms)

You don't see this directly, but it's why the product *feels* alive:

1. You (or Mo, or an agent, or a rule) change something — say, you move a due date.
2. That single click **atomically** creates three things at once: the actual data change, a permanent activity record (with enough detail to undo it), and an event describing what happened.
3. That event immediately does several things in parallel, live, with no polling:
   - Anyone else looking at that task or project sees the change **appear on their screen within moments**, with no refresh.
   - It lands in the assignee's Inbox if it's relevant to them.
   - If a rule is watching for exactly this kind of change, it fires (and if that rule's action creates *another* change, that one goes through the same three-part write, capped so an automation loop can't spiral forever).
   - If the task's text changed, it's quietly re-indexed so Mo's search and Ask Mo can find it later.
   - Once agents exist, this is also how an agent decides to wake up and act (e.g. a new task lands in a triage-enabled project and Sorter picks it up within a minute).

This one mechanism — "every change is a small, complete, replayable fact" — is what makes realtime collaboration, notifications, automation rules, search, and agents all consistent with each other instead of four separate systems that can silently disagree about what actually happened.

---

## 12. Who can see and do what

Every piece of data belongs to exactly one **workspace** (your organization). Inside it: **teams** own **projects**; a project has its own member list and roles (viewer / editor / admin-ish "owner"); a task inherits its visibility from the project(s) it's placed in, plus anyone explicitly added as a follower/collaborator gets task-only access even without full project membership. Every permission check — whether it's a person clicking a button, Mo answering a question, or an agent proposing a change — runs through the *same* check. If you try to open something you can't see, you get an honest "you don't have access" message with a hint of who to ask, never a confusing error or a silent 404 that looks like the thing doesn't exist.

---

## 13. It doesn't have to live only here

Momentum was deliberately designed to run in three different situations without being rebuilt for any of them:

1. **Standalone** — its own app, its own web address. This is how the team uses it day to day.
2. **Lift-and-shift** — the exact same app, moved wholesale to a different environment (say, a different Azure tenant later on), with data exported/imported as a portable bundle and identities re-linked by email.
3. **Embedded inside another product** — Momentum's backend can be mounted as a sub-application inside a *different* company tool, and its entire UI can be dropped into a *different* React app under a sub-path (e.g. `yourapp.com/momentum/...`), reusing that host's own login instead of Momentum's. From a user's point of view, this means: if your organization later decides work management shouldn't be its own separate app but a tab inside some other internal system, Momentum can become that tab without anyone rebuilding the task list, the AI assistant, or the agents from scratch.

Practically, this also means Momentum came from — and can migrate real data from — **Asana**: there's a real importer (and a CSV importer for anything else), so switching over doesn't mean starting from zero.

---

## 14. What's real today vs. what's still on the roadmap

Momentum is being built in phases, each one a fully working slice — nothing described above as "shipped" is a mockup. As of the last status update, here's where things actually stand:

| Phase | What it delivers | Status |
|---|---|---|
| 0 — Foundations | App shell, login, design system | ✅ Done |
| 1 — Core tasks MVP | Teams/projects/sections/tasks/subtasks, list view, task pane, comments, activity, undo, My Tasks, Home | ✅ Done |
| 2 — Daily-use parity | Board & calendar views, custom fields, tags, multi-homing, dependencies, milestones, realtime updates, notifications/inbox, attachments, search, Asana/CSV import | ✅ Done |
| 3 — AI layer v1 ("Mo") | LLM gateway, ⌘K natural-language commands, Ask Mo chat, summaries, break-into-subtasks, status drafts, plan-my-day, project-from-brief, semantic search | ✅ Done — live-tested against the real model gateway |
| 4 — Workflow and intake | Rules (+ NL rules, AI steps), forms (+ conversational intake), project/task templates (+ AI template generation), approvals, recurring tasks | ✅ Done (exit criteria met) |
| 5 — Agents v1 | Agent runtime, agents as assignable/mentionable teammates, the 8 starter agents, Runs UI, budgets, autonomy promotion/demotion | ⏳ Not started — next up, pending go-ahead |
| 6 — Planning and insight | Timeline/Gantt, project overview, portfolios, goals, workload, dashboards, "ask for a chart," forecasting/risk score | ⏳ Not started |
| 7 — Integrations | Slack, Outlook calendar, email-to-task, outgoing webhooks (MCP server explicitly dropped by the product owner) | ⏳ Not started |
| 8 — Hardening | Installable app (PWA), performance work, export/import, security review, accessibility, admin tooling | ⏳ Not started |
| 9 — Deploy and go-live | Real Azure deployment, real login, importing the team's real Asana data, cutover | ⏳ Not started |

A note on scope: the product owner has explicitly reserved certain customer-operations capabilities (things like pricing/contract/invoice tooling and pushes into other internal systems) to be built later in a *separate* codebase — they are intentionally **not** part of Momentum's roadmap.

---

## 15. The experience, summed up

You open a familiar list of teams, projects, and tasks and are productive in five minutes because it looks and behaves like the tool you already knew. The difference shows up the moment something tedious would normally happen: instead of writing the status update yourself, you review one someone (something) already drafted from real data; instead of remembering to chase three overdue teammates, a nudge already went out this morning; instead of building a project skeleton field by field, you paste in a paragraph and get a full plan to approve. Every one of those assists is visible, attributed, reversible, and — if the AI ever goes down — entirely optional, because the task manager underneath it all works exactly as well without a single word of AI in the loop.

---

## 16. One full user story, every feature, everything built

*The scenario below assumes every phase (0–9) is finished and the team has fully cut over from Asana. It's written as one continuous story so every feature in this document appears in the natural place it would actually get used — nothing here is out of order or contrived. Character: **Ana**, a project manager at a 12-person team that makes and ships a B2B product. Supporting cast: **Ravi** (designer), **Priya** (engineer), **Sam** (team lead), **Lena** (workspace admin), and Momentum's own teammates — **Mo**, **Pulse**, **Sorter**, **Herald**, **Nudge**, **Architect**, **Scribe**, **Radar**.*

### Monday, 7:40am — the day starts before Ana opens her laptop

Overnight, **Pulse** (the Daily Digest agent) already ran. When Ana opens Momentum, **Home** greets her — "Good morning, Ana" — with Mo's one-line brief in amber: *"You have 4 tasks due today; the Q3 Launch project is at risk; 2 approvals are waiting on you."* Her **My priorities** card lists her top 5 tasks by due date and priority; **Recent projects** shows the six she actually touched last week; **Waiting on others** flags a design review she's been following that's now overdue on Ravi's plate, so she doesn't have to remember to check; and **Agent activity** shows a scroll of what her AI teammates did overnight — Sorter triaged three new requests, Nudge sent one polite nudge, Radar flagged one project.

She also got the same digest as a **Slack DM**, since she has notifications set to both in-app and Slack. She didn't have to open Momentum at all to know today looked busy.

### 8:00am — turning a hallway idea into a task, and a chat into a project

Walking past Ravi's desk, someone mentions the customer wants a bulk-export feature. Ana hits `Q` and types straight into quick-add:

> `Bulk export for reports @ravi next friday #q3-launch !high`

Momentum parses it locally with no AI at all — assignee Ravi, due next Friday, project "Q3 Launch," priority High — and the remaining text becomes the clean task title "Bulk export for reports." She adds one more line that doesn't parse into tidy tokens: *"needs a scoping doc from Priya before Ravi can start, cc the account team once it's live."* The amber **"✦ Let Mo fill in the details"** button appears; she clicks it, Mo reads the sentence, proposes adding Priya as a follower, a dependency once a scoping-doc task exists, and a comment tagging the account team — all shown as a preview, nothing applied until she confirms.

Back at her desk, she pastes in three paragraphs from a client kickoff call — timestamps, rambling, half-formed. Rather than parse it herself, she assigns it to **Scribe**. Within a minute Scribe posts a comment: a clean decisions list, and five real action-item tasks, each with an owner (resolved from the attendee names in the notes) and a due date, linked back to the source. She reviews them — no fabricated owners, nothing invented that wasn't in the notes — and they're live.

### 9:15am — a big ask, handled with one paragraph

Sam (team lead) drops a one-paragraph brief in Slack: *"We need a customer-facing status page project — public-facing incident history, an internal alerting hook, and a review gate before anything alerting-related goes to prod."* Ana forwards it into Momentum and hands it to **Architect**. Architect comes back with a full plan preview: sections ("Design," "Build," "Review," "Launch"), a dozen tasks with suggested dates fitting the requested window, and suggested assignees drawn from team membership and skill tags — all as one reviewable proposal, nothing created yet. Ana edits two dates, removes one placeholder task, and clicks Apply. The whole project exists, correctly structured, in under two minutes — created via **"Project from brief,"** with a **Rules engine** and a **template** already wired in because she chose "review gate before prod" from a template menu that Architect matched to an existing "Launch with review gate" project template (one that was itself originally generated by **"Template from description,"** months ago, and now just gets reused).

### 10:00am — the process runs itself

The status-page project has a **form** for outside stakeholders to request changes, set to **conversational intake** — instead of a wall of fields, a requester gets a short natural back-and-forth ("What kind of change is this?" → "Which environment?") that ends in a confirm step before anything is created. A request comes in through it. **Sorter** picks it up the moment the resulting task is created (a `task.created` / `form.submitted` event fires it within the minute): it sets Type and Priority fields, checks for duplicates against everything already open (catching one near-duplicate and posting a linking comment instead of creating a second task), and suggests an assignee — since the project's triage autonomy has been promoted to **auto** (it earned that: 85%+ acceptance over its last 30 proposals, no undos in two weeks), the field-setting applies immediately and only the assignee suggestion needs Ana's nod.

A plain-English **rule** Ana wrote weeks ago — *"When a task in this project is marked complete and it's in the Launch section, notify the project owner and tag it 'shipped'"* — fires automatically the moment someone finishes a launch task; she never has to remember to check.

The project also has an **approval** task gating the alerting change: it sits as `pending`, shows up in Ana's own task lists exactly like any other task, and when Sam clicks Approve, an `approval.decided` event fires a rule that notifies the requester automatically. Momentum never lets an agent decide an approval on anyone's behalf — that's a strictly human action.

Two tasks in the launch checklist are **recurring**: a weekly security-scan task that regenerates itself every Monday on a fixed schedule, and a "renew the SSL cert" task that only spawns its next occurrence once the current one is marked done.

### 11:30am — the cross-project view

Ana switches to **Timeline** on the Q3 Launch project: bars for every task, diamonds for the two milestones, arrows showing which tasks block which, a "today" line, and a faint marker showing the **forecast** — Momentum's nightly Monte-Carlo simulation, run against the team's real historical throughput, puts a P80 finish date about four days later than the stated due date. She drags one blocking task two days later to accommodate a dependency; Momentum previews the cascade — every downstream task's proposed new date — before she commits to it as one batch (fully undoable if she changes her mind).

She flips to **Portfolios**: a table of every active project she owns or watches, each with owner, status, percent complete, due date, and a one-line AI summary of the latest activity. Q3 Launch shows amber because **Radar** flagged it that morning — the flag itself gives named reasons: one blocked chain three tasks deep, one unassigned task close to due, and the forecast slipping past the stated due date. She clicks through, and it's exactly the reasons Radar named, not a vague "at risk" with no explanation.

Under **Goals**, the quarterly goal "Ship status-page and bulk export" is linked to two of these projects; its progress bar is computed automatically from their completion percentage, and Mo's periodic check-in narrative reads, in plain sentences, what actually moved this goal forward this week — citing real tasks, not generic filler.

### 1:00pm — who's overloaded, and fixing it before it's a problem

Sam opens **Workload**: a people-by-weeks grid. Priya's cells for next week are solid red — she's double-booked against her stated capacity, partly because she's out for two days (her Outlook OOO synced in automatically and reduced her capacity for those days). Sam clicks **"✦ Suggest rebalance"**; Mo proposes moving two of Priya's lower-priority tasks to a teammate with matching skill tags and free capacity, shown as one reviewable batch of reassignments and date shifts. Sam applies it. Nobody sent a single "can you take this" message.

### 2:00pm — reporting without writing a report

Friday's status update doesn't wait for Friday this week — Ana `@mentions` **Herald** directly in the project's Overview tab and asks for an early draft. Herald reads the real activity window — what completed, what slipped (with the old and new dates, pulled straight from the activity trail), what's blocked, what's next — and posts a draft, marked amber, with every claim citing a real task key. Ana reviews it, tweaks one sentence, and publishes it as the project's official status update; the status also rolls up automatically into the **Portfolio**'s aggregated status draft that Sam will use in his own leadership update.

She also builds a quick **Dashboard** widget — a donut of open tasks by assignee — but for a one-off question she doesn't want to build a widget for, she just asks Mo directly: **"how many tasks did we complete last week that were originally scheduled for two weeks ago?"** — Mo turns that into a validated query spec, shows a preview chart, and offers "Add to dashboard" if she wants to keep it.

### 3:30pm — nobody has to leave Slack

A client emails the shared project inbox (`q3-launch+<token>@yourcompany.com`) with a change request attached as a PDF; it becomes a task automatically, attachment text extracted and indexed so it's searchable later. In Slack, someone right-clicks a message with a good idea and uses **"Create Momentum task"** — a modal opens prefilled with the message text, they pick a project and assignee, and it posts back a link into the same Slack thread. When Ana later pastes a Momentum task URL into a different Slack channel, it unfurls into a rich preview automatically — but only for people whose linked Momentum account can actually see that task; nothing leaks past permissions. An external monitoring tool the ops team runs is wired to Momentum's **outgoing webhooks**, so a signed, retried delivery notifies it the moment any task in the "Incidents" project is created.

### 4:15pm — Ana looks something up she barely remembers

She half-remembers a conversation from two months ago about a pricing edge case, but not which task it was on. She asks Ask Mo: *"what did we decide about the annual-plan proration edge case?"* Mo's hybrid search — combining meaning-based similarity and keyword matching — finds the actual comment thread (which by now is long enough that she's shown the cached AI summary of it rather than 40 raw comments), cites the task key, and answers in two sentences instead of her spending ten minutes scrolling.

### 5:00pm — undoing a mistake, cleanly

Ana bulk-reassigns 40 tasks to the wrong person after misreading a filter. She hits **⌘Z**. All 40 revert, in one action, with no support ticket and no manual cleanup — because the bulk change was written as one batch with one undo payload the moment it happened, exactly like every other change in the product, human or AI.

### Evening — the parts nobody in the office ever sees

Overnight, jobs run quietly: embeddings re-index anything that changed today so tomorrow's search and Mo answers stay current; the forecast simulation re-runs against today's real throughput; **Nudge** scans for anything overdue or stalled and leaves a polite comment (never on anything blocked by someone else's unfinished work, never more than once every two days on the same task, escalating to the project owner after three nudges with no response); a maintenance job expires any AI proposal nobody acted on within 24 hours; and the digest scheduler queues up tomorrow's Pulse run for every user's own chosen time.

### Behind the scenes, once a quarter — Lena's job as admin

Lena, the workspace admin, doesn't touch any of the above. Her view is **Settings → Admin**: members and roles (inviting a new hire, disabling someone who left), teams, the AI panel (enable/disable per feature, read-only view of which model alias powers what, the workspace's monthly AI budget and current spend, workspace memory), agent policy (which agents are enabled workspace-wide, and who's allowed to promote an agent to `auto`), integrations (the Slack app connection, the Graph calendar app registration), background jobs (a place to see any job that failed permanently, so nothing silently rots), and import (the original Asana cutover, still there for reference).

The whole application is installable as a **PWA**, works acceptably offline for reading (edits queue and reconcile once reconnected, never silently lost), passed an accessibility and security review before go-live, and — because every environment fact (URLs, model names, tenant ids) lives in configuration rather than code — the exact same application was later deployed to the company's production Azure environment with nothing rewritten, just reconfigured. Nobody on the team, from Ana to Lena, ever had to think about any of that; from where they sit, Momentum is just the place work happens, with an assistant and a small crew of teammates who never forget to update the status, never forget to nudge the overdue task, and never touch anything without showing their work first.
