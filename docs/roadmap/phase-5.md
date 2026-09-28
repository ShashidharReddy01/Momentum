# Phase 5: Agents v1 ("Teammates")

**Goal:** agents as first-class teammates: configurable, scoped, budgeted, auditable. Eight starter agents running. Milestone **M4**.

**Read first:** ai/agents.md, ai/ai-architecture.md §4, §8.

**Exit criteria:** J10 passes; at least 3 starter agents run on schedule in dogfood for a week with ≥ 70% proposal acceptance; the budget cap stops a runaway agent (test); the runs page explains every action.

**Kickoff (2026-09-28):** see `phase-5-kickoff.md` for the state check, refinements and the product owner's answers. In short:
- Built and tested in **mock mode**; `momentum llm-check` and `EVALS_LIVE=1 make evals` are deferred to the product owner's machine.
- The dogfood criterion is a **post-ship observation**, read as: Pulse, Herald and Sorter run on their triggers for a week; acceptance ≥ 70% across the agents that propose (Pulse makes no proposals).
- **Access:** an agent sees only what its own account is granted (explicit project membership as an editor, visible in Share). Scope narrows, never grants. Per-user agents (Pulse) run on behalf of the recipient.
- **Autonomy defaults:** the `agents.md` §4 table; workspace "allow medium auto" off; external-content triggers capped at `confirm`.
- **Budgets:** Pulse $10/month, others $5 (custom $5); a `budget_monthly_tokens` fallback (default 2M) applies while the agent's model is unpriced; per-run ceilings 15 steps / 300 s always.
- **Order:** E5.1 → S5.2.1 + S5.3.8 (J10) → S5.2.2 → S5.2.3 → Pulse, Sorter, Herald, Nudge, Radar → Architect, Scribe. `momentum agents install` installs all 8 **disabled**.
- **Carried from Phase 4:** S5.0.1 (inbox/bell live updates) before S5.1.3; S5.0.2 (forms security review) before S5.3.2; check the J1 quick-entry flake first.
- **Extension points (product owner, 2026-09-28; ADR-0009):** the owner's own codebase will add customer-operations tools, agents and scripts. New S5.1.5 (host tools and agent definitions, code-backed `handler` agents, `get_attachment_text`) and S5.1.6 (API tokens, moved from S7.1). S5.1.1/S5.1.2 are shaped for them from the start (`agents.kind`, loader directories).

## E5.0 Carried from Phase 4

### S5.0.1: Inbox and bell live updates
**Scope:** subscribe `/inbox` and the topbar bell to `user:<id>` so `notification.created` appears without a reload (gap found at the Phase 4 exit). Agents deliver through notifications (`agent_proposal`, `digest`, `agent_alert`), so this lands before S5.1.3.
**Size:** S

### S5.0.2: Public forms security review
**Scope:** review S4.2.1's public form endpoints: member-name exposure on assignee questions; `X-Forwarded-For` handling for the per-IP rate limit (trusted-proxy setting). Fix what the review finds. Before S5.3.2, because Sorter acts on form submissions.
**Size:** S

---

## E5.1 Runtime

### S5.1.1: Agent model and accounts
**Scope:** migrations `agents`, `agent_runs`; agent user accounts (`is_agent`), avatars; YAML definitions loader and "install starter agents" command; admin CRUD API.
**Kickoff refinements:** migration 0028 adds `agents`, `agent_runs` (unique `dedupe_key`), `agents.budget_monthly_tokens`, FK `users.agent_id → agents` and the deferred FK `llm_calls.agent_run_id → agent_runs`, and the `agent_alert` notification kind. Agents are disabled, never deleted. `momentum agents install [--only KEY]` is idempotent by `key`, installs **disabled**, and never overwrites an admin's edits (reports drift). Enabling an agent for a project adds its account as a project editor. `agents.kind` (`llm` default | `handler`) + `agents.handler` (ADR-0009). The definitions loader takes extra directories from the app factory (host agents).
**Size:** M

### S5.1.2: Runtime loop and triggers
**Scope:** `agents/runtime.py` per agents.md §2; triggers: schedule (Procrastinate periodic → per-agent cron evaluation in workspace/user timezone), event (outbox consumer with filters), assigned, mentioned, manual; dedupe keys; step/time limits; trace recording; policy application (autonomy × risk).
**AC:** the same trigger delivered twice runs once; an agent with a $0.01 budget stops with `budget_exceeded` and notifies the admin.
**Kickoff refinements:** reuse `ai/loop.py` with a policy hook (autonomy × risk) instead of a second loop. Service-level guards: an agent can't complete a task assigned to a human, delete anything, or decide approvals. External-content triggers (`form.submitted`, later email/Slack) are capped at `confirm`. Workspace timezone in `workspaces.settings['timezone']` (default `UTC`). `croniter` becomes an explicit dependency. Settings `MOMENTUM_AGENTS_ENABLED`, `MOMENTUM_AGENT_MAX_STEPS` (15), `MOMENTUM_AGENT_TIMEOUT_S` (300). The token fallback budget applies while the agent's model is unpriced.
**Size:** L

### S5.1.3: Runs UI
**Scope:** `/agents/runs/:id` timeline (steps, tool calls, result digests, proposals with apply/reject, cost, errors); agent detail run history with filters.
**Size:** M

### S5.1.4: Autonomy, budgets, kill switches
**Scope:** per-agent autonomy setting with promotion stats (agents.md §5), budget settings, per-agent enable, global AI switch, auto-demotion job.
**Kickoff refinements:** the global switch already exists (`MOMENTUM_AI_ENABLED` + the S3.5.2 admin override); add `allow_medium_auto` (default off) to the workspace AI config. Promotion is admin-only; acceptance stats per agent double as the dogfood measurement.
**Size:** M

### S5.1.5: Extension points and code-backed agents
**Scope (ADR-0009):** the app factory accepts host tools (→ `build_registry`), host agent-definition directories and `handlers={name: fn}`. The runtime runs `kind: handler` agents: it calls the registered Python callable with a run context (the triggering entity, a services session as the agent account, `llm` handle counted against the budget, `step()` for the trace, `propose()` for confirm-style output, helpers to comment and attach a file). Same triggers, dedupe, timeout, kill switches and runs page as `llm` agents. New read tool `get_attachment_text` (permission-checked, capped, `<data>`-wrapped). An example handler agent under `tests/` (not shipped as a starter). INTEGRATION_GUIDE "Extending agents" section + change log.
**AC:** an assigned task runs a handler agent and the result comment appears with ✦ and an undo; an unregistered handler fails the run with a clear error; a handler that exceeds its timeout is stopped; a host tool is callable by a host `llm` agent.
**Size:** M

### S5.1.6: API tokens (moved from S7.1)
**Scope (ADR-0009):** token auth as an `AuthProvider` alongside Easy Auth/dev (`Authorization: Bearer mtm_…`), using the existing `api_tokens` table (hashed, prefix shown, scopes, expiry, revoke, `last_used_at`); personal tokens in profile settings (shown once); admins can issue a token for an agent account so an external script acts as that agent; scopes (`tasks:read`, `tasks:write`, `attachments:write`, …) narrow normal permissions; writes carry `via="api"`. Docs: "Calling Momentum from a script".
**AC:** a token without `tasks:write` can't create tasks; a revoked or expired token gets 401; tokens never appear in logs; a script using an agent's token creates a task that shows the agent as its author.
**Size:** M

## E5.2 Agents as teammates

### S5.2.1: Assign a task to an agent
**Scope:** agents appear in AssigneePicker (✦ ring); assignment triggers a run; the result is posted as a comment (long output → attachment); task moves to "Review" section if present, else reassigned to creator; @mention the requester.
**Size:** M

### S5.2.2: @mention an agent
**Scope:** mentions of agent users trigger a run with thread context; reply in the thread.
**Size:** S

### S5.2.3: Agent gallery + create from description
**Scope:** `/agents` gallery; "Create agent" form; "✦ Describe what you want" → Mo drafts the definition (instructions, triggers, tools, autonomy) → review → save; test run on a chosen task/project (dry-run).
**Size:** M

## E5.3 Starter agents (one slice each, size M unless noted)

| Slice | Agent | Notes |
|---|---|---|
| S5.3.1 | Pulse · Daily Digest | Per-user schedule at `prefs.digest_time` (default 08:30 weekdays in the user's timezone); no digest when there's nothing to report; runs on behalf of the recipient; inbox digest item; email/Slack delivery hooks for P7 |
| S5.3.2 | Sorter · Triage | Enabled per project (= its `scope.projects`); uses semantic duplicates; `confirm` default; capped at `confirm` on `form.submitted`. After S5.0.2 |
| S5.3.3 | Herald · Status Reporter | Reuses S3.4.3 prompt; weekly schedule; owner publishes |
| S5.3.4 | Nudge · Nudger (S) | Rate limits per task; escalation to owner; respects snooze: per-task "Snooze nudges until…" (`my_task_placements.nudge_snoozed_until`) and a user-level "don't nudge me" pref; skips tasks blocked by others' open work |
| S5.3.5 | Architect · Planner | Wraps S3.4.6 with capacity awareness hooks (full in P6) |
| S5.3.6 | Scribe · Meeting Notes | Paste/upload notes (txt, md, docx, vtt); decisions + action items; email-in hook (P7) |
| S5.3.7 | Radar · Risk Watcher | Heuristic risk signals now; forecast integration in P6 |
| S5.3.8 | Teammate (generic) (S) | Base behavior for assigned/mentioned work |

Each starter-agent slice includes: YAML definition, prompt, tool allow-list, mock fixtures, eval cases with thresholds (agents.md §4), and docs update.
