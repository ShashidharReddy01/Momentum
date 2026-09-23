# Vision and Scope

## 1. Vision

**Momentum keeps work moving.** It gives a small team (10–15 people) Asana's familiar way of organizing work: teams → projects → sections → tasks → subtasks, seen as list, board, calendar, or timeline. It removes the "work about work" with **Mo**, an assistant available on every screen, and with **agents** that act as teammates.

**One-line pitch:** *Asana's layout, with an assistant that does the updating, summarizing, chasing, and planning for you.*

## 2. Personas

| Persona | Needs | Momentum's answer |
|---|---|---|
| **Team member** | Know what to do today; fast capture; few notifications | My Tasks + "Plan my day"; quick-add in natural language; AI-ranked inbox and daily digest |
| **Project owner / PM** | Plan, track, report, chase | Templates, list/board/timeline, AI status drafts, Nudger and Risk Watcher agents |
| **Team lead / manager** | Workload, priorities, cross-project view | Workload view, portfolio-lite, weekly AI brief |
| **Ops / admin** | Intake, automation, consistency | Forms + conversational intake, rules in plain English, templates, approvals |
| **Executive / stakeholder** | Status without asking | Portfolio summaries, goals with AI narrative, Slack digests |
| **Workspace admin** | Users, access, AI cost | Admin settings, roles, AI budgets and usage |

## 3. Product principles

1. **Familiar first.** Anyone who has used Asana is productive in 5 minutes.
2. **Less clicking, more asking.** `⌘K` accepts commands and natural language everywhere.
3. **AI drafts, humans confirm, the system remembers.** Every AI change is previewed, attributed, and can be undone.
4. **Agents are teammates.** They're members that can be assigned, @mentioned, and reviewed.
5. **Honest UI.** Never fabricate data. AI content is marked amber, mock data is marked purple (dev only).
6. **Simple to run and move.** One image, one database, config-only environment changes, and the ability to be embedded in another project.

## 4. Scope matrix

| Area | Feature | Phase | Notes |
|---|---|---|---|
| Core | Workspace, teams, projects, sections, tasks, subtasks | 1 | |
| Core | Assignee, start/due dates, description (rich text), followers | 1 | NL dates |
| Core | Comments, @mentions, reactions, activity feed, undo | 1 | |
| Core | My Tasks, Home | 1 | |
| Core | Board, calendar views | 2 | |
| Core | Custom fields, tags, multi-homing, dependencies, milestones | 2 | |
| Core | Realtime, notifications, inbox, attachments, search | 2 | |
| Core | Asana importer, CSV import | 2 | Real data only in the office environment |
| AI | Command bar NL, Ask Mo chat, summaries, subtasks, status drafts, plan my day, project from brief, semantic search | 3 | |
| Workflow | Rules (+NL rules, AI steps), forms (+conversational intake), templates, approvals, recurring tasks | 4 | |
| Agents | Framework, agents as teammates, 8 starter agents, runs page, budgets | 5 | |
| Planning | Timeline/Gantt, overview, portfolio-lite, goals-lite, workload, dashboards, forecast | 6 | |
| Integrations | MCP server, Slack, Outlook calendar (Graph), email-to-task | 7 | |
| Hardening | PWA, performance, export/import, security, a11y, admin | 8 | |
| Deploy | Azure (App Service, Easy Auth, PG Flexible, Blob, App Insights), go-live | 9 | |
| **Out of scope** | SSO/SAML config UI, SCIM, audit-log API, EKM, data residency, guests (maybe later), proofing, video, time tracking, native mobile apps, billing | – | Revisit after v1 |

## 5. Success metrics

| Metric | Target |
|---|---|
| Weekly active users | ≥ 90% of the team within 4 weeks of go-live |
| Asana licenses | 0 after go-live + importer |
| Tasks with owner + due date | ≥ 85% |
| Weekly AI usage (command bar / Mo) | ≥ 60% of users |
| Agent proposal acceptance | ≥ 70% |
| Time on status updates | −50% (survey) |
| p95 list interaction latency | < 200 ms perceived (optimistic) |

## 6. Glossary

| Term | Meaning |
|---|---|
| **Workspace** | Top-level tenant (one organization). Every row carries `workspace_id`. |
| **Team** | Group of users that owns projects |
| **Project** | Container of sections and tasks, with views, fields, rules, and forms |
| **Section** | Ordered group within a project (a column on the board) |
| **Task** | Unit of work. Types: `task`, `milestone`, `approval`. Can be multi-homed in several projects. |
| **Subtask** | Task with `parent_id` |
| **Multi-homing** | One task belonging to several projects, each with its own section and position |
| **Activity** | Immutable record of a change (who, what, diff, undo payload) |
| **Outbox event** | Row written in the same transaction as a change. Drives realtime, rules, agents, notifications. |
| **Mo** | The AI assistant persona (chat, command bar, inline actions) |
| **Agent** | Configured AI teammate with instructions, tools, scope, autonomy, and budget |
| **AI action** | A proposed or applied change made by AI, with preview and undo |
| **Autonomy** | `suggest` (comment only) · `confirm` (propose, human applies) · `auto` (applies low/medium risk) |
| **Model alias** | `fast`, `default`, `smart`, `embed`. Mapped to real models by configuration. |
| **Slice** | Thin vertical increment (DB → API → UI → tests → docs) delivered in about 1–3 days |
