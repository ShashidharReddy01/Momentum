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

## Summary

On features, Momentum already exceeds Asana's basic plans, especially AI, forecasting, and the features Asana keeps for Advanced. Asana still leads on mobile apps, integrations, and product maturity. Phase 6.5 (UI/UX) and Phase 9 (integrations) target those gaps.
