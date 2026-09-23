# Phase 5: Agents v1 ("Teammates")

**Goal:** agents as first-class teammates: configurable, scoped, budgeted, auditable. Eight starter agents running. Milestone **M4**.

**Read first:** ai/agents.md, ai/ai-architecture.md §4, §8.

**Exit criteria:** J10 passes; at least 3 starter agents run on schedule in dogfood for a week with ≥ 70% proposal acceptance; the budget cap stops a runaway agent (test); the runs page explains every action.

---

## E5.1 Runtime

### S5.1.1: Agent model and accounts
**Scope:** migrations `agents`, `agent_runs`; agent user accounts (`is_agent`), avatars; YAML definitions loader and "install starter agents" command; admin CRUD API.
**Size:** M

### S5.1.2: Runtime loop and triggers
**Scope:** `agents/runtime.py` per agents.md §2; triggers: schedule (Procrastinate periodic → per-agent cron evaluation in workspace/user timezone), event (outbox consumer with filters), assigned, mentioned, manual; dedupe keys; step/time limits; trace recording; policy application (autonomy × risk).
**AC:** the same trigger delivered twice runs once; an agent with a $0.01 budget stops with `budget_exceeded` and notifies the admin.
**Size:** L

### S5.1.3: Runs UI
**Scope:** `/agents/runs/:id` timeline (steps, tool calls, result digests, proposals with apply/reject, cost, errors); agent detail run history with filters.
**Size:** M

### S5.1.4: Autonomy, budgets, kill switches
**Scope:** per-agent autonomy setting with promotion stats (agents.md §5), budget settings, per-agent enable, global AI switch, auto-demotion job.
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
| S5.3.1 | Pulse · Daily Digest | Per-user schedule at `prefs.digest_time`; inbox digest item; email/Slack delivery hooks for P7 |
| S5.3.2 | Sorter · Triage | Enabled per project; uses semantic duplicates; confirm autonomy default |
| S5.3.3 | Herald · Status Reporter | Reuses S3.4.3 prompt; weekly schedule; owner publishes |
| S5.3.4 | Nudge · Nudger (S) | Rate limits per task; escalation to owner; respects "snooze" |
| S5.3.5 | Architect · Planner | Wraps S3.4.6 with capacity awareness hooks (full in P6) |
| S5.3.6 | Scribe · Meeting Notes | Paste/upload notes (txt, md, docx, vtt); decisions + action items; email-in hook (P7) |
| S5.3.7 | Radar · Risk Watcher | Heuristic risk signals now; forecast integration in P6 |
| S5.3.8 | Teammate (generic) (S) | Base behavior for assigned/mentioned work |

Each starter-agent slice includes: YAML definition, prompt, tool allow-list, mock fixtures, eval cases with thresholds (agents.md §4), and docs update.
