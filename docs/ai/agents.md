# Agents

Agents are AI teammates: configured, scoped, budgeted, auditable, and visible as members.

## 1. Agent definition

```yaml
key: status_reporter
name: Herald · Status Reporter
avatar: herald
description: Drafts weekly project status updates from real activity.
instructions: |
  Every Friday, for each project in scope, draft a status update covering: what was completed,
  what slipped, blockers, and what's next. Base every statement on activity data and cite task keys.
  Set status on_track / at_risk / off_track using the rubric below. …
triggers:
  - { type: schedule, cron: "0 15 * * FRI", timezone: workspace }
  - { type: mentioned }                        # "@Herald draft a status for this project"
tools: [get_project, get_project_activity, search_tasks, create_status_update]
scope: { projects: "member_of" }              # or explicit ids / teams
autonomy: confirm                             # suggest | confirm | auto
model_alias: default
budget_monthly_usd: 5
limits: { max_steps: 12, timeout_s: 300 }
```

Definitions for starter agents live in `momentum/agents/definitions/*.yaml`. A workspace install copies them into the `agents` table (editable). A custom agent is created from the UI (or "create agent from description", which Mo drafts).

## 2. Runtime

```
trigger (schedule | outbox event | assigned | mentioned | manual)
  → enqueue agent_run (queue "ai", dedupe key per agent+trigger+entity)
  → runtime.run(agent, trigger):
      ctx = Ctx(user=agent.user, via="agent")
      budget check
      messages = [system(agent persona + base rules + instructions + memory), user(trigger context)]
      loop ≤ max_steps:
         completion = llm.complete(alias, messages, tools=allowed_tools)
         for each tool call:
             read tool → execute, append result
             write tool → registry.preview → policy(autonomy, risk):
                  apply now | create ai_action (proposed) | post suggestion comment
         if final answer → post output (comment / status draft / DM) → break
      record trace, tokens, cost → agent_run.finished event
```

- **Idempotency:** a scheduled run for the same period isn't repeated (dedupe key `agent:period`).
- **Concurrency:** one active run per agent per entity.
- **Failure:** retries only for transient gateway errors. A final failure posts nothing to users, is visible in the Runs page, and alerts the admin if it repeats.
- **Kill switch:** `enabled=false` on an agent, `MOMENTUM_AI_ENABLED=false` globally.
- **Trace:** each step stores a short `summary`, tool name, args (redacted), result digest, tokens. Never full prompts unless debug capture is on.

## 3. Assignment and mention behavior

- **Assigned a task:** the agent reads the task and its context, does the work (research/draft/summarize/plan), posts the result as a comment (and attachment if long), moves the task to a "Review" section if one exists or reassigns it to the task creator, and @mentions them.
- **@mentioned in a comment:** replies in the thread. If the request implies changes, it follows autonomy rules.
- Agents never complete tasks assigned to humans, never decide approvals, and never delete.

## 4. Starter agents

| # | Agent | Trigger | Context | Tools | Output | Default autonomy | Eval |
|---|---|---|---|---|---|---|---|
| 1 | **Pulse · Daily Digest** | Weekdays at each user's digest time | User's tasks due today/overdue, new assignments, mentions, changes on followed tasks since the last digest | read tools | Inbox digest item + Slack DM (P7) + optional email | auto (read-only) | Coverage: all due/overdue items listed; no hallucinated tasks |
| 2 | **Sorter · Triage** | `task.created` in projects with triage enabled; `form.submitted` | New task, similar tasks (semantic), project fields and members, triage rules text | search, semantic_search, update_task, set_field_value, add_comment | Fields set (type/priority), suggested assignee, duplicate link comment | confirm (upgradeable to auto) | Accuracy vs labeled set ≥ 80%; duplicate precision ≥ 90% |
| 3 | **Herald · Status Reporter** | Fri 15:00; @mention | Project activity window, overdue/blocked, milestones | get_project_activity, search_tasks, create_status_update | Draft status update (amber) for the owner to publish | confirm | Factuality: every claim cites real keys; status rubric agreement ≥ 80% |
| 4 | **Nudge · Nudger** | Daily 10:00 | Tasks overdue > 1 day or stale (no activity 5+ days, not done) | search_tasks, add_comment | Polite comment to the assignee; escalate to the owner after 3 nudges; max 1 nudge per task per 2 days | auto (comments only) | Tone check; no nudges on completed/blocked-by-others tasks |
| 5 | **Architect · Planner** | Manual ("Plan this" on a brief/task/project) | Brief text, templates, team members, capacity (P6) | create_project_from_plan, create_subtasks | Plan preview (sections, tasks, dates, suggested assignees) | confirm | Structure validity; dates within the requested window; no unknown assignees |
| 6 | **Scribe · Meeting Notes** | Manual paste/upload of notes/transcript; email-in (P7) | Notes text, attendees → users, related projects | search_tasks, create_task, add_comment | Decisions list + action items as tasks with owner/due; link back | confirm | Action-item recall ≥ 85% on fixtures |
| 7 | **Radar · Risk Watcher** | Daily 08:00 | Per project: overdue ratio, blocked chains, unassigned near-due, scope growth, forecast (P6) | read tools, add_comment | Risk note on the project overview + digest line for owners | suggest | Flags known-risky fixture projects; false-positive rate ≤ 20% |
| 8 | **Teammate (generic)** | Assigned / mentioned | Task + context + retrieval | read tools + add_comment, create_subtasks | Work product in comments | confirm | Rubric-graded helpfulness on fixtures |

## 5. Autonomy promotion

An admin can promote `confirm → auto` for an agent when its **acceptance rate ≥ 85% over the last 30 proposals** and there were no undo events for 14 days. The UI shows these stats next to the toggle. Demotion is automatic if the undo rate goes above 10% in a week.

## 6. Agent UI surfaces

See `frontend/ux-specs.md` §9. Every agent action in the product shows: agent avatar (amber ring), "✦ via Herald", a "Why?" tooltip (trigger + summary), and Undo when applicable.
