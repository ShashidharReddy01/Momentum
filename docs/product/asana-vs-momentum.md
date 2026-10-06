# Asana vs Momentum (basic plans)

**As of 2026-10-01**, end of Phase 6 (UI revamp, Phase 6.5, in progress). The comparison is against Asana's **Personal** (free, up to 10 people) and **Starter** (about $11–13 per user per month) plans, from public knowledge of Asana's pricing. Asana changes plan contents often: check asana.com/pricing before relying on any line here. Update this file at each phase exit.

## What Asana has that we don't

| | Asana | Momentum | Plan to close |
|---|---|---|---|
| Mobile apps | Native iOS and Android apps, plus desktop apps | Responsive web only | Phase 6.5 (phone layouts); no native app planned |
| Integrations | 100+ (Slack, Teams, Gmail/Outlook, Google Drive, Zoom, Zapier) | Asana and CSV import, API tokens | Phase 9, after go-live: Slack first; Outlook calendar, email-to-task, outgoing webhooks later |
| Calendar sync | Google/Outlook calendar export | None | Phase 9 (Outlook via Microsoft Graph) |
| Maturity | Years of polish, offline support, large-scale reliability, vendor support | New; planned for ~150 people in one workspace (Phase 7 load-tests 150 accounts) | Phase 6.5 (UI), Phase 7 (hardening), Phase 8 (Azure go-live) |
| Project messages | A Messages tab per project | Task comments and project status updates | Not planned |

## What we have that Asana's basic plans don't

| | Momentum | Asana (Personal / Starter) |
|---|---|---|
| Portfolios, Goals, Workload | Included | Advanced plan or higher |
| Rules | No monthly cap; written in plain English; can include an AI step | Starter caps rule actions per month |
| AI chat (Ask Mo) | Answers about your workspace with linked sources, scoped to what you can see | Asana AI exists, more limited and metered on low plans |
| AI actions | ⌘K commands in plain English, previewed → applied → undoable; smart quick-add; writing help | Not comparable |
| AI agents as teammates | Assign tasks or @mention them; budgets, autonomy levels, kill switches | Not on basic plans (AI Studio is a paid add-on) |
| AI for planning | Project or template from a brief, conversational intake forms, goal check-in drafts, workload rebalancing, "ask for a chart" | — |
| Completion forecasts | Likely finish dates with a range (Monte Carlo on your team's throughput), shown on the timeline and overview; 75% backtest accuracy | — |
| Undo | Undo on every change, including AI changes | Limited |
| Dashboards | Workspace and project dashboards; click any mark to open its tasks | Project dashboards on Starter |
| Approvals, forms, templates, milestones, dependencies, timeline | Included, with dependency-aware rescheduling | Mostly Starter; some limited |
| Data and cost | Self-hosted in your Azure tenant, no per-seat fee, choice of AI provider (model aliases), export anytime, embeddable in other apps | Per-seat SaaS; data hosted by Asana |

## Parity checklist (Phase 7, E7.0 / E7.4)

What someone moving off Asana reaches for on their first days, feature by feature. **Have** means it works the way an Asana user expects (the import carries it over too, S7.4.2); **partial** says what differs; **missing** gives the decision. Decisions were delegated to the AI by the product owner (2026-10-04) and are listed for review.

| Asana feature | Momentum | Decision / where |
|---|---|---|
| Tasks, subtasks (nested), sections | Have | Subtasks up to 5 levels |
| Assignee, due date and time, start date | Have | |
| List, board, calendar, timeline views | Have | Timeline with dependencies and forecast cone (S6.1.1) |
| Custom fields (text, number, single/multi select, people, date, checkbox) | Have | Filter, sort, group and chart by them (S7.4.1) |
| Tags | Have | Undoable (H53) |
| Multi-homing (a task in several projects) | Have | S2.4.1 |
| Dependencies, milestones, approvals | Have | Dependency-aware rescheduling (S6.1.2) |
| Recurring tasks | Have | Month-end and leap-day rules (H31) |
| Followers / collaborators, comments, @mentions, likes | Have | Reactions on comments; likes import as reactions |
| Attachments | Have | Script-carrying files never render (H47) |
| **Duplicate task** | Have (new) | E7.4: copy right below with subtasks, fields and tags, one undo; comments, attachments and dependencies aren't copied (Asana's defaults) |
| Duplicate project | Have, as a template | Project ⋯ → Save as template → new project from it (keeps sections, tasks, rules, roles) |
| **Export project to CSV** | Have (new) | E7.4: Asana's column names, subtasks after their parent, custom fields as columns, spreadsheet-formula safe; reimports through CSV import |
| Import from CSV | Have | S2.7.2 |
| Import from Asana | Have | Full, resumable, idempotent (S7.4.2) |
| My Tasks with sections, Inbox, notifications | Have | |
| Search with filters | Have | Incl. custom fields; saved searches: partial, see below |
| Saved searches / reports | Partial | Dashboards with click-through to tasks cover reports (S6.5.1); a saved search list is not built. **Later** (post go-live feedback) |
| Project overview, brief, status updates | Have | |
| Portfolios, goals, workload, dashboards | Have | Asana Advanced features |
| Rules | Have | No monthly cap; plain-English rules |
| Forms | Have | Public link, conversational intake |
| Templates (project and task) | Have | |
| Keyboard shortcuts | Have | Asana's keys without Tab (S7.4.4) |
| Teams, private projects, guests | Have | Guests see only shared projects and their people (H61) |
| Admin console (members, roles, deactivate, audit) | Have | S7.5.4 |
| Dark mode | Have | |
| Export all data | Have | Admin export bundle (S7.5.1) |
| Mobile apps | Missing | **Later** (product owner, 2026-10-01): responsive web works on phones |
| Integrations (Slack, Teams, email-to-task, calendar sync), webhooks | Missing | **Phase 9**, after go-live; Slack first |
| Time tracking (actual time) | Partial | Effort estimates and workload exist; actual time logging **Later** |
| Out of office | Missing | **Later**: workload capacity per week covers planning around absence |
| Mark as duplicate of another task | Missing | **Later**: close one and link it in a comment |
| Proofing (comments on an image) | Missing | **Later** (Asana Business tier) |
| Project Messages tab | Missing | Not planned: task comments and status updates cover it |
| AI (Asana AI) | Have, more | Ask Mo, ⌘K commands, agents as teammates |

## Summary

On features, Momentum already exceeds Asana's basic plans, especially AI, forecasting, and the features Asana keeps for Advanced. Asana still leads on mobile apps, integrations, and product maturity. Phase 6.5 (UI/UX) and Phase 9 (integrations) target those gaps.
