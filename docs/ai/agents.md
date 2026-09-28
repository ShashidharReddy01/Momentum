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

**As built (S5.1.1):**
- **Schema:** `domain/agents/schemas.AgentDefinition` validates files, and the same `AgentConfig` validates the admin API, so a file and a UI-made agent obey one set of rules. Beyond the example above: `kind` (`llm` default, or `handler` + `handler`: a host-registered function, ADR-0009), `budget_monthly_tokens` (default 2M; the cap while the model is unpriced, kickoff Q4), `limits` capped by `MOMENTUM_AGENT_MAX_STEPS`/`MOMENTUM_AGENT_TIMEOUT_S`. Cron triggers must be 5-field and valid; `timezone` is `workspace`, `user` (each user's own, for per-user agents) or an IANA name. Tools must exist in the registry, and `delete_task`/`decide_approval` are refused on every agent.
- **Files:** one per agent, named `<key>.yaml`; keys are unique across Momentum's starters and any host directories (`create_app(agent_definition_dirs=…)`, `mount_momentum(…)`, or `momentum agents install --definitions-dir`). A host can't replace a starter; it defines its own keys.
- **Install:** `momentum agents install [--only KEY] [--force]` or `POST /api/v1/agents/install` (admins). Idempotent by key: new → `installed`, **disabled** (kickoff Q3); same definition → `unchanged`; a changed definition updates an agent nobody edited (`updated`); an agent an admin edited is `drifted` and kept unless `--force`. `enabled` is never touched by an install. `momentum agents list` shows the result.
- **Accounts:** each agent gets its own user (`is_agent`, email `<key>@agents.momentum.invalid`) that never signs in. **Access is explicit project membership** (kickoff Q1): `POST /agents/{id}/projects {project_id, role}` (needs admin on that project, undoable), never through teams or the admin role; `scope` only narrows. See `architecture/auth-and-permissions.md` §8.
- **API:** `GET /agents` (members), `GET /agents/{id}` (with the projects it can access that *you* can see), `POST /agents` (custom, admins, disabled until enabled), `PATCH /agents/{id}` (admins; `kind`/`handler`/`key` can't change), `POST/DELETE /agents/{id}/projects[/{project_id}]`. Agent changes record activity and `agent.created`/`agent.updated` events, no undo payload (configuration, like rules).
- **Starter defaults (kickoff Q2, Q4):** autonomy as in the §4 table; Pulse $10/month, the others $5; `model_alias` `fast` for Sorter and Nudge, `smart` for Architect, `default` otherwise. Their instructions are first charters; each starter slice (S5.3.x) refines its own agent's instructions and adds its evals.

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

**As built (S5.1.2):** `momentum/agents/triggers.py` → `domain/agents/runs.py` → `momentum/agents/runtime.py`, run by two jobs (`jobs/agents.py`): `agent_triggers` (every minute) and `run_agent_runs` (every minute, queue `momentum_ai`). So an agent starts **within a minute** of its trigger.
- **Triggers → queued runs**, each with a dedupe key unique per agent (`agent_runs.dedupe_key`): `schedule:<n>:<user|->:<minute>`, `event:<outbox id>`, `assigned:<task>:<outbox id>`, `mentioned:<comment>`, `manual:<uuid>`. The same trigger delivered twice queues once.
  - **Schedules:** evaluated for the current and the previous minute, in the workspace timezone (`workspaces.settings['timezone']`, default UTC, `PUT /workspace/settings`), a fixed IANA zone, or `user` (one run per active person, in their own timezone, acting on their behalf). A minute the worker missed entirely is not replayed.
  - **Events, assignments and mentions:** an outbox consumer (`consumer_offsets` row `agents`). Only events from after the agent was last enabled count (`agents.enabled_at`, migration 0029). Events caused by an agent never trigger an agent (loop protection). Event triggers fire only inside the agent's access and scope; assigned/mentioned/manual always queue, and a missing access fails the run with an explanation.
  - **Manual:** `POST /agents/{id}/run {task_id?, project_id?, text?}` (any member who can see the target; the agent must be enabled and have a `manual` trigger).
- **Per run:** kill switches (`MOMENTUM_AGENTS_ENABLED`, the agent's `enabled`; AI master and workspace switches in the gateway) → acting context (the agent's account, or the recipient's for a `for_user_id` run) → access and scope check → the shared tool loop (`ai/loop.py`) with only the agent's tools, `limits` capped by the `MOMENTUM_AGENT_*` ceilings, a wall-clock timeout, and `agent_run_id` on every model call → the policy → an answer in the task's thread when a person asked → trace, tokens, cost, `agent_run.finished`.
  - One active run per agent per task/project (`claim_runs`). A run stuck past its timeout is failed, never retried blind.
- **Policy (`agents/policy.py`, ai-architecture §4):** read tools run. Writes are previewed in the loop; afterwards each is applied as the agent (`auto` + low risk; medium only if the workspace allows it, S5.1.4), proposed to the run's person (`ai_actions`, `source="agent"`, `source_id` = the run, an `agent_proposal` notification), or turned into a suggestion (`suggest` agents; their own `add_comment` calls are the suggestion channel and are posted). External content (a task created by a form, `via` = `form`/`integration` on the event) caps autonomy at `confirm`. A per-user run never writes on the person's behalf unasked (its "apply" becomes "propose").
  - When a person applies an agent's proposal, it runs **with their permissions**, marked `via="agent"`, and the activity rows carry `ai_action_id`. This also settles S5.1.1's question: an agent-proposed project is created by the person who applies it, so no agent becomes a project admin.
  - An agent's auto-applied action can be undone by the person it was for (`undo_action` → `core.undo(also_by=agent)`), with that person's own project permissions.
- **Who proposals go to** (`trigger.requested_by`): the assigner, the comment author, whoever pressed Run; for events the person who caused them (else the project owner); for per-user schedules the person. A plain schedule with no person proposes nothing; S5.3.x agents that need it fan out per project.
- **Budgets:** checked by the gateway before every agent call (`UsageLog.check_budget(agent_run_id=…)`): the workspace budget, then the agent's own. **Dollars while its model is priced, tokens while it isn't** (kickoff Q4); 0 = unlimited. Over budget → the run stops with `budget_exceeded`, the call is recorded with that status, nothing is posted, and workspace admins get an `agent_alert` (at most once a day per agent).
- **Failures:** the run keeps a plain-language error, and its writes roll back. Three failed runs in a row alert the admins (same throttle). Agent-authored comments are `is_ai` (fixed in S5.1.2: `via="agent"` wasn't counted before).
- **Service guards (agents.md §3):** agents can't delete anything (tasks, comments, attachments, sections, projects, teams, tags, forms, rules, templates: `access.forbid_agent`), can't complete a task assigned to someone else, and can't decide approvals (S4.4.1).
- **Not yet:** handler agents fail with "No handler is registered" until S5.1.5. The runs UI is S5.1.3; the Review-section move and the @mention of the requester on assignment are S5.2.1.

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
