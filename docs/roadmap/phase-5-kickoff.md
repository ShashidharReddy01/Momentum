# Phase 5 Kickoff

**Date:** 2026-09-28 · **Model:** Opus 5.5 (whole phase, per `docs/process/model-guide.md` §2) · **Phase goal:** agents as first-class teammates: configurable, scoped, budgeted, auditable. Eight starter agents running (M4).

**Status:** kickoff written; **all §5 questions answered 2026-09-28 by the product owner (every recommendation accepted)**. §3's refinements are applied to `phase-5.md`. CLAUDE.md §6 areas (permission semantics, AI autonomy defaults) are settled by those answers.

## 1. Kickoff prerequisite: mock mode

This session's environment has no LLM gateway access (cloud container, no `.env`). As in Phase 3 (`phase-3-kickoff.md` §1), **the whole phase is built and tested with `MOMENTUM_LLM_MODE=mock`**:

- The real gateway code path stays exercised: tests drive the real OpenAI SDK against the in-process fake OpenAI-compatible server; every agent gets YAML mock fixtures; `make evals` runs in mock mode by default.
- **No slice blocks on live gateway access.**
- **Deferred to a later local session on the product owner's machine** (not blocking any slice): `momentum llm-check` against the real Portkey gateway, and `EVALS_LIVE=1 make evals` at phase exit.
- **The dogfood exit criterion** ("at least 3 starter agents run on schedule in dogfood for a week with ≥ 70% proposal acceptance") is a post-ship observation period. It is **deferred, not blocking**: the phase ships the measurement (acceptance stats per agent, S5.1.4) so the week can be read off the product afterwards.

## 2. State check (code vs. phase file)

Baseline on `claude/intelligent-meitner-9ne4e8`, fast-forwarded to the Phase 4 exit commit (`300bbc7`): `make check` green, **594 backend / 311 web**.

| Area | What Phase 5 assumes | Reality after Phase 4 | Consequence |
|---|---|---|---|
| `momentum/agents/` | Runtime, definitions, loader | Empty package (`__init__.py` only) | S5.1.1/S5.1.2 create it |
| `users.is_agent`, `users.agent_id` | Agent accounts | **Both columns exist since migration 0001**; `agent_id` has no FK (the `agents` table doesn't exist). `Ctx.actor.is_agent` and `actor_kind="agent"` are wired through activity, events, rules and forms. People listings (`GET /users`, `list_people`, mentions search, invites) **exclude agents** today | S5.1.1 adds `agents` + the FK. S5.2.1/S5.2.2 must deliberately let agents back into the AssigneePicker and mention search (and only there) |
| `agents`, `agent_runs` tables | data-model.md §9 | Specified in `docs/architecture/data-model.md`, not created | S5.1.1 migration 0028. `llm_calls.agent_run_id` (no FK since S3.1.1) gets its FK then; `ai_feedback.target_type='agent_run'` becomes usable; `ai_actions.source='agent'` already allowed |
| Agent guards in services | "Agents never complete humans' tasks, never decide approvals, never delete" (agents.md §3) | Only `decide_approval` refuses agents (S4.4.1). `complete_task` and `delete_task` don't check `is_agent` | Enforce the other two **in services** (S5.1.2), not only by leaving tools off allow-lists: the model is never the security boundary (ai-architecture §8) |
| Tool loop | agents.md §2 loop | `ai/loop.py` (shared by ⌘K and chat) runs read tools and turns write tools into previews collected for **one** `ai_actions` row. `actions.py` supports `source="agent"`; `approved` state reserved for agent `confirm` flows | The runtime reuses `ai/loop.py` with a **policy hook** (autonomy × risk → apply now / propose / suggestion comment) rather than a second loop |
| Limits | agents: 15 steps, 5 min (ai-architecture §10) | Chat uses `MAX_STEPS = 8`, 60 s. Starter YAML example says `max_steps: 12, timeout_s: 300` | Per-agent `limits` from the definition, clamped to 15 / 300 s ceilings |
| Budgets | Per-agent monthly USD budget; "$0.01 budget stops with `budget_exceeded`" | Only the **workspace** budget exists (`DbUsageLog.check_budget`). Cost comes from `MOMENTUM_LLM_PRICE_TABLE`; **unpriced models cost $0, and the product owner's price table is not set** ("dollar cost unmeasured", Phase 3 exit). Mock calls report estimated tokens, so tests can price them | Per-agent budget = sum of `llm_calls.cost_usd` joined through `agent_runs` for the month. **In production today an agent's dollar cap would never trip** → Q4 |
| Kill switches | Per-agent enable, global AI switch | Global switch exists twice: `MOMENTUM_AI_ENABLED` (env) and the admin override `workspaces.settings['ai'].enabled` (S3.5.2). `AiConfig.allow_auto_apply` exists; no "allow medium auto" | S5.1.4 reuses both switches; adds `agents.enabled` and a workspace `allow_medium_auto` override (default off, per ai-architecture §4) |
| Scheduling | Procrastinate periodic → per-agent cron in workspace/user timezone | Periodic jobs exist (rules, ai steps, embeddings every minute). `croniter` is present **only as a transitive dependency** of Procrastinate. **No workspace timezone** anywhere (`users.timezone` exists) | One `run_agent_schedules` periodic job (every minute) evaluates each enabled agent's crons. Make `croniter` an explicit dependency (same reasoning as `pyyaml` in S3.1.1). Workspace timezone goes in `workspaces.settings['timezone']` (default `UTC`, no migration) |
| Event triggers | Outbox consumer with filters | Rules (`rules`) and embeddings (`embeddings`) are outbox consumers with their own `consumer_offsets` rows; rules have loop protection | Agents get their own consumer (`agents`). Dedupe key `agent:trigger:entity[:period]` as a unique index on `agent_runs` |
| Mentions / assignment | Triggers `assigned`, `mentioned` | `task.assigned` event and comment mention extraction exist; both only target humans today | S5.2.1/S5.2.2 subscribe through the agents consumer |
| Notifications | `agent_proposal`, `digest` kinds; admin alert on budget/failure | `agent_proposal` and `digest` are already in the check constraint (0011/0022). No kind for "agent needs attention" | Add an `agent_alert` kind for admin alerts in S5.1.2 (check-constraint change in migration 0028) |
| Pulse digest time | `prefs.digest_time` | `digest_time` exists in the notification-preferences schema (S2.5.3) | Pulse reads it; users without one get a default (Q5) |
| Sorter "enabled per project" | Per-project triage switch | Projects have **no settings column** | Use Sorter's own `scope.projects` as the switch (no migration, one source of truth) |
| Nudge "respects snooze" | A snooze | **No snooze concept exists** | Q7 |
| "Review" section | Move task to Review if present | No convention | Match a section named "Review" (case-insensitive) in the task's project; else reassign to creator |
| Frontend | `/agents`, runs UI, ✦ ring in pickers | **Nothing** agent-related in `apps/web` (no route, no placeholder). `is_agent` is in the generated API types | S5.1.3 / S5.2.3 add routes; the amber ✦ accent already exists for AI content |
| Tool catalog | agents.md §4 tool lists | **Corrected in S5.1.1:** `set_field_value`, `create_rule`, `request_approval` and `decide_approval` are in ai-architecture's catalog but were never registered (Sorter needs `set_field_value` → S5.3.2). The rest are registered: `search_tasks`, `semantic_search`, `get_project_activity`, `create_status_update`, `update_task`, `set_field_value`, `add_comment`, `create_subtasks`, `create_project_from_plan`, `create_task` | No new tools needed for the starter set, except a read tool for Pulse's "changes since the last digest" (S5.3.1) |
| J10 | "Assign task to Teammate agent → result comment → review" (testing-strategy.md) | Not written | Needs S5.2.1 + S5.3.8; see Q3 on ordering |

**Lessons from earlier retros that apply here:**
- Phase 4: when `domain/rules/schemas.py`'s vocabulary changes, check `ai/nl_rule.py` in the same slice. Phase 5 adds agent-related events (`agent_run.finished`); if rules may trigger on them, the parity test will demand it.
- Phase 4: when a UI journey fails, isolate the backend with a direct API call first (J10 will involve the worker, like J9).
- Phase 4: the inbox/bell has no live subscription. Agents deliver mostly through notifications (`agent_proposal`, `digest`), so this gap hits Phase 5 directly → Q6.
- Phase 2/3: E2E journeys create journey-scoped data; fixtures need at least two of whatever the code chooses between (two candidate agents, two mentions).
- Phase 4: the rules executor's cron ticks once a minute of real wall-clock; the agent scheduler inherits the same granularity. J10 uses the `assigned` trigger, not a schedule, so it doesn't wait on the clock.

## 3. Refinements (proposed; applied to `phase-5.md` once §5 is answered)

| Slice | Change | Reason |
|---|---|---|
| S5.1.1 | Migration 0028: `agents`, `agent_runs` (+ unique `dedupe_key`), FK `users.agent_id → agents`, FK `llm_calls.agent_run_id → agent_runs`. Agents are soft-disabled, never deleted (runs and activity keep pointing at them) | data-model.md §9; the deferred FKs from S3.1.1 |
| S5.1.1 | `momentum agents install [--only KEY]` CLI, idempotent by `key`; a re-install never overwrites an admin's edits (it reports drift instead) | Definitions are "copied into the table (editable)" (agents.md §1) |
| S5.1.2 | The runtime is `ai/loop.py` plus a policy hook, not a second loop. Service-level guards: agents can't complete a task assigned to a human, can't delete, can't decide approvals | One tool-calling loop; the model is never the security boundary |
| S5.1.2 | New notification kind `agent_alert` (budget exceeded, repeated failure, auto-demotion) → workspace admins | No existing kind fits |
| S5.1.2 | `croniter` becomes an explicit dependency | Already installed transitively; the runtime would depend on it directly |
| S5.1.2 | Workspace timezone in `workspaces.settings['timezone']` (default `UTC`) | `timezone: workspace` in agent crons has nothing to read today |
| S5.1.4 | Reuse the existing global switches; add `agents.enabled` and workspace `allow_medium_auto` (default off). Auto-demotion is a daily periodic job | ai-architecture §4 already reserves "unless the workspace allows medium auto" |
| S5.3.2 | Sorter's "enabled per project" is its `scope.projects` list | No project settings column; avoids two switches for one thing |
| S5.3.2 | Sorter on `form.submitted` runs **capped at `confirm`** for writes regardless of its autonomy (ai-architecture §8, external content) | Already a rule; restated because Sorter is the first agent it applies to |
| New settings | `MOMENTUM_AGENTS_ENABLED` (env kill switch for the agent scheduler/consumer, like `MOMENTUM_RULES_ENABLED`), `MOMENTUM_AGENT_MAX_STEPS` (15), `MOMENTUM_AGENT_TIMEOUT_S` (300) | Ceilings from ai-architecture §10 become settings; docs + `.env.example` |

## 4. Risks

| Risk | Mitigation |
|---|---|
| Runaway cost while the price table is unset (caps never trip) | Q4; hard per-run step/time ceilings regardless; `llm-check`'s `pricing` row already warns |
| Agents acting on untrusted text (form submissions, comments that @mention an agent) | `<data>` wrapping; external-content triggers capped at `confirm`; tools enforce permissions; eval cases with injection attempts for Sorter, Teammate and Scribe |
| Duplicate runs (event redelivered, scheduler overlap, a worker restart mid-run) | Unique `dedupe_key`; one active run per agent per entity; tests deliver the same trigger twice (S5.1.2 AC) |
| Noisy agents erode trust (Nudge, Radar) | Rate limits per task, conservative autonomy defaults (Q2), auto-demotion on undo rate, everything visibly marked ✦ with "Why?" |
| Permission leakage through an agent account that can see "everything" | Q1: agents see what their account is granted, nothing implicit; per-user agents act on the recipient's visibility |
| Mock mode hides real-model tool-calling behavior over long agent loops | Fake OpenAI server tests; the deferred `EVALS_LIVE=1` run at exit; record mode to turn real runs into fixtures later |

## 5. Questions for the human

Recommendations first; the answers go in here and in STATUS "Open questions".

- **Q1 (permissions semantics): how does an agent account get access to data?** Recommendation: **an agent sees only what its own account is granted**, like a person. Scope (`member_of` / explicit projects / teams) *narrows* what it acts on but never grants access. Installing an agent adds it to nothing; enabling it for a project adds its account as a project **editor** (visible in the Share dialog, removable like anyone). Per-user agents (Pulse) run **on behalf of the recipient** (`ctx.user` = recipient, `via="agent"`), so a digest can only contain what that person can already see. Alternative: scope grants implicit read access (simpler, but invisible and wider).
  **Answered 2026-09-28: explicit membership** (as recommended).
- **Q2 (autonomy defaults per starter agent):** Recommendation: **accept the agents.md §4 table**: Pulse `auto` (read-only; writes only its own digest notification), Sorter `confirm`, Herald `confirm`, Nudge `auto` limited to comments, Architect `confirm`, Scribe `confirm`, Radar `suggest`, Teammate `confirm`. Plus: workspace "allow medium auto" **off**; external-content triggers capped at `confirm`; promotion `confirm → auto` only by an admin, at ≥ 85% acceptance over the last 30 proposals with no undos in 14 days; automatic demotion above 10% undo rate in a week. Alternative: start Nudge at `confirm` too (its comments go to the assignee as proposals first) until dogfood shows its tone is right.
  **Answered 2026-09-28: the agents.md §4 table** (as recommended), including medium-auto off, external-content cap, promotion and demotion rules.
- **Q3 (which agents, in what order, installed how):** Recommendation: runtime first (S5.1.1–S5.1.4), then **S5.2.1 + S5.3.8 Teammate** together (that's J10), then S5.2.2, S5.2.3, then the scheduled/event starters **Pulse → Sorter → Herald → Nudge → Radar**, then Architect and Scribe. `momentum agents install` installs all 8 **disabled**; an admin enables each. **Dogfood trio: Pulse, Herald, Sorter.** Note the exit criterion's tension: Pulse (auto, read-only) makes no proposals, so the ≥ 70% acceptance figure would be measured on Herald and Sorter (and Teammate if used); Sorter is event-triggered, not scheduled. Proposed reading: "3 starter agents run on their triggers for a week; acceptance ≥ 70% across the agents that propose."
  **Answered 2026-09-28: the recommended plan** (order, install disabled, dogfood trio Pulse/Herald/Sorter, acceptance measured on the agents that propose).
- **Q4 (budget caps):** Recommendation: per-agent monthly caps from the YAML (**Pulse $10** since it runs per user per weekday, **the others $5**, custom agents default $5), counted in USD from `llm_calls`, **and** an optional per-agent `budget_monthly_tokens` fallback that applies when the agent's model has no price in `MOMENTUM_LLM_PRICE_TABLE`, so a cap always means something even before you set prices (default 2M tokens/month per agent). Hard per-run ceilings (15 steps, 5 min) always apply. Also: set the price table before dogfood so the usage page shows dollars. Alternative: dollars only, and refuse to enable an agent in gateway mode while its model is unpriced.
  **Answered 2026-09-28: USD caps + token fallback** (Pulse $10, others $5, 2M-token fallback when unpriced, per-run ceilings always).
- **Q5 (Pulse default digest time):** users with no `digest_time` get **08:30 in their own timezone, weekdays**; the digest is skipped when there's nothing to report (no empty digests). Recommendation: yes.
  **Answered 2026-09-28: yes** (08:30 weekdays in the user's timezone, no empty digests).
- **Q6 (carried-forward items):** Recommendation: fold two into Phase 5 before the agents that need them: **(a) the inbox/bell live-update gap** as a small pre-slice before S5.1.3 (agent proposals and digests arrive as notifications, so a stale inbox would hide them); **(b) the forms security review** (member-name exposure, `X-Forwarded-For`) before S5.3.2, because Sorter will act on form submissions. Look at **the J1 quick-entry flake** first thing (never build on a flaky baseline) and fix it if it reproduces here. Keep **deferred**: conversational-intake eval coverage and the per-turn spam counter (not on Phase 5's path).
  **Answered 2026-09-28: fold the two** (inbox/bell live update before S5.1.3; forms security review before S5.3.2); check the J1 flake first; the other two stay deferred.
- **Q7 (Nudge snooze):** no snooze exists. Recommendation: a per-user, per-task **"Snooze nudges until…"** on the assignee's own task row, stored on `my_task_placements` (already per user per task; one nullable column), plus a user-level "don't nudge me" pref. Nudge also skips completed tasks and tasks blocked by someone else's open work.
  **Answered 2026-09-28: per-task snooze on `my_task_placements` + a user-level "don't nudge me" pref** (as recommended).
- **Q8 (added after the kickoff, 2026-09-28): make agents extensible for the owner's customer-operations work?** Context: the product owner's own codebase will add SQQ, discovery, invoice, contract and data-upload agents and scripts. Recommendation: add host tools and agent definitions, code-backed `handler` agents, API tokens (moved from S7.1) and a `get_attachment_text` tool to Phase 5. That is cheap now and expensive to retrofit after eight agents. Onboarding-specific workflow features (conditional template items, template versions applied to running projects, agent pre-fill of forms, document generation) stay out of the roadmap.
  **Answered 2026-09-28: yes** ("add them in the phases"). The product owner will do customer onboarding later and wants the base kept flexible. Recorded in **ADR-0009**; new slices S5.1.5 and S5.1.6 in `phase-5.md`.
- **Q9 (raised while building S5.1.3, 2026-09-29): when a person assigns, @mentions or runs an agent, what may the agent see?** Recommendation: only what both the agent and that person can see (lower role of the two); scheduled and event runs keep the agent's own access.
  **Answered 2026-09-29: only what both see** (as recommended). Built in S5.1.3 via `ctx.acting_for`.

## 6. Exit criteria (as written, with the deferrals above)

- J10 passes (mock).
- The budget cap stops a runaway agent (automated test; a $0.01 budget with a priced mock model).
- The runs page explains every action (trace step per tool call, proposal, cost, error).
- Deferred to the product owner's machine: `momentum llm-check`, `EVALS_LIVE=1 make evals`.
- Deferred, post-ship: 3 starter agents on their triggers in dogfood for a week at ≥ 70% acceptance.
