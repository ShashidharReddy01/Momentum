# Phase 4: Workflow and Intake

**Goal:** automation that people can write in plain English, intake that asks the right questions, reusable templates, approvals, and recurring work.

**Exit criteria:** J9 passes; rule loop protection proven; 20 NL rule phrases compile correctly (evals); a form → triage → assignment flow works end to end.

---

## E4.1 Rules engine

### S4.1.1: Rule model and executor
**Scope:** migrations `rules`, `rule_runs`; rule JSON schema:
```json
{ "trigger": {"type": "task.moved", "to_section": "…"},
  "conditions": [{"field": "priority", "op": "eq", "value": "high"}],
  "actions": [{"type": "assign", "user_id": "…"}, {"type": "add_comment", "text": "…"}] }
```
Triggers: task added to project, moved to section, field changed, completed, assigned, due date approaching (job), form submitted, approval decided. Conditions: field ops (eq, neq, in, empty, not_empty, gt/lt for numbers/dates), assignee, tag. Executor consumes outbox events; actions run through services with `ctx.via="rule"`, `actor_kind=rule`.
**Loop protection:** max depth 3 (events caused by rules carry depth), max 50 rule actions per minute per project, same rule can't fire twice on the same event.
**AC:** a chain A→B→C→A stops at depth 3 with a logged skip.
**Size:** L

**Built (2026-09-27):** migration 0021 (`rules`, `rule_runs`), `domain/rules/` (`models`, `schemas`, `service`, `engine`, `router`), job `run_rules` (every minute). API: `GET/POST /rules` (`?project_id=`), `GET/PATCH/DELETE /rules/{id}`, `GET /rules/{id}/runs`. Triggers built: task added, moved to section (an actual section change), field changed (priority, due/start date, custom field; optional `to`), completed, assigned (optional person). **Not built, refused on write:** due date approaching (needs a scanning job; S4.1.2), form submitted (S4.2.1), approval decided (S4.4.1). Conditions: eq, neq, in, empty, not_empty, gt, lt on priority, assignee, due/start date, tag, custom fields. Actions built (just enough to prove the executor; S4.1.2 adds the rest): assign, add comment, move to section, mark complete. Events carry `depth`; loop protection, rate limit and per-event dedupe are as in `realtime-jobs-events.md` §5. New setting `MOMENTUM_RULES_ENABLED`. Rule actions run as the rule's author (`via="rule"`, `actor_kind=rule`); only project admins manage project rules.

### S4.1.2: Actions library
**Scope:** set field, assign, move section, add to project, remove from project, add tag, add comment, create subtasks (from list), mark complete, set due relative ("+3 days"), notify user (inbox), Slack message (enabled in P7), AI step (S4.1.5).
**Size:** M

**Built (2026-09-27):** migration 0022 (adds notification kind `rule`); 7 new actions in `domain/rules/engine.py` — `set_field` (priority or a custom field id, via `update_task`/`set_task_field_value`), `add_to_project`/`remove_from_project` (via the multi-homing service; `add_to_project`'s `section_id` is optional and, if given, is checked against the *target* project, not the rule's own), `add_tag` (idempotent, like the API), `create_subtasks` (a list of titles, each becomes a subtask of the triggering task), `set_due_relative` (`days` in the rule author's timezone via `today_for`), `notify_user` (inbox only; kind `rule`, title truncated to the column's 300 chars). `slack_message` and `ai_step` are accepted by name but refused on write (`NOT_YET_ACTIONS`) until P7/S4.1.5. Trigger `task.due_approaching` built: `jobs/due_approaching.py` (hourly, `momentum_maintenance` queue) calls `domain/rules/due_scan.py`, which emits the event for tasks due tomorrow (UTC), deduped per (task, due date) against `events_outbox` so it fires once no matter how many scans happen before the executor consumes it. `form.submitted`/`approval.decided` triggers still refused (S4.2.1/S4.4.1).

### S4.1.3: Rule builder UI and run history
**Scope:** project "Rules" (⋯ → Rules): list with toggles, builder (trigger → conditions → actions with pickers), readable sentence preview, run history with status and errors, test-run on a chosen task (dry-run).
**Size:** L

**Built (2026-09-27):** backend: `POST /rules/{id}/test-run` (`RuleTestRunIn`/`RuleTestRunOut`/`ActionResultOut` in `schemas.py`) — conditions are checked, then each action runs as the rule's author inside its own savepoint that's always rolled back (`engine.test_run`), so a later action still gets tried even if an earlier one fails and nothing is ever persisted; `service.test_run_rule` needs the same "admin" permission as editing the rule plus a visible task (`get_visible_task`). Frontend: `apps/web/src/momentum/features/rules/` — `RulesDialog` (list, enable/disable toggle, inline create/edit, delete), `RuleBuilder` (trigger → conditions → actions pickers built from hand-kept metadata mirroring `TRIGGER_PARAMS`/`ACTION_PARAMS`/`ACTION_REQUIRED`, live readable-sentence preview), `RuleRunHistory` (run history list + "Test on a task…" picker showing per-action ok/error). Wired into `ProjectPage.tsx` (⋯ → Rules, admin-only). `lib/realtime/handlers.ts` now handles `entity_type: 'rule'` (invalidates the project's rule list; `rule.ran` also invalidates that rule's run history). `slack_message`/`ai_step` are left out of the action picker (refused on write until P7/S4.1.5).

### S4.1.4: NL → rule
**Scope:** `POST /ai/rules/compile` → rule JSON (validated) + readable sentence; ambiguous references ask back; saved with `created_from_prompt`.
**AC:** 20 fixture phrases → correct JSON (≥ 90% exact, rest ask for clarification rather than guess).
**Size:** M

**Built (2026-09-27):** `momentum/ai/nl_rule.py` + `prompts/nl_rule/v1.md` (`default`, temperature 0) + `POST /ai/rules/compile` (`RuleCompileIn` → `RuleCompileOut`: either `rule` (exactly what `POST /rules` accepts, including `created_from_prompt`) + `sentence`, or a `question`, never both). The model answers in **names**, not ids: it gets a `<data source="project">` reference block (the project's sections, people, tags and attached custom fields, plus the names of up to 40 other visible projects) and the server resolves every name inside that project's own scope — the same scope `service._check_references` validates. Anything unresolvable or ambiguous (`match_person` never picks between two people) becomes a question instead of a guess, as does a phrase the engine can't express (Slack, AI steps, relative due-date comparisons) or one the model itself flagged; the draft is finally validated by building a real `RuleIn`, and a validation failure is reported as a question too. Permission: `service.authorize_manage` (new), the same **admin** check `create_rule` does, before any model call. Nothing is saved here: `RulesDialog` sends the draft through the normal create call, prefilled and editable in `RuleBuilder` (`draft` prop, amber "Mo drafted this" header, hidden while AI is off). Evals: feature `nl_rule`, 20 cases (`rule_exact` compares the compiled rule with names in place of ids), thresholds mock 1.0 / live 0.9; the eval workspace now seeds two tags. **AC met:** the live run scored **20/20** — 18 phrases compiled to exactly the expected JSON, 2 asked back (Slack, a section that doesn't exist). An earlier 18/20 run found a real gap: the reference block listed no other projects, so `add_to_project`/`remove_from_project` could never resolve.

### S4.1.5: AI step action
**Scope:** action type `ai_step` with sub-kinds: summarize to comment, classify into field, extract fields from description, draft reply comment. Runs on the `ai` queue; writes marked AI; subject to the risk policy (field writes = low).
**Size:** M

## E4.2 Forms and intake

### S4.2.1: Form builder
**Scope:** migrations `forms`, `form_submissions`; builder (title, description, questions mapped to task title/description/fields/assignee/due, required, branching v1 (show question if answer = X)), internal link (logged-in) and public link (`/f/:token`, excluded path, rate limited, honeypot + optional captcha later); submission creates a task in the chosen section; `form.submitted` event.
**AC:** a public form works without login; spam limits enforced.
**Size:** L

### S4.2.2: Conversational intake
**Scope:** form option "Conversational": chat UI asks the form's questions naturally and follows up when answers are vague (fast alias), then shows a summary for confirmation, then submits. All answers are still mapped to fields.
**AC:** the resulting task is equivalent to a classic submission (same fields); the transcript is attached as a comment.
**Size:** M

## E4.3 Templates

### S4.3.1: Project templates
**Scope:** migration `templates`; "Save as template" (sections, tasks, subtasks, relative dates from project start, roles instead of people, fields, rules); "New from template" (pick start date, map roles → people).
**Size:** M

### S4.3.2: Task templates
**Scope:** per-project task templates (title pattern, description, subtasks checklist, fields); "+ Add task ▾ from template".
**Size:** S

### S4.3.3: Template from description (AI)
**Scope:** describe the process → template preview → save.
**Size:** S

## E4.4 Approvals and recurring tasks

### S4.4.1: Approvals
**Scope:** task type `approval`; approver = assignee; actions Approve / Request changes / Reject (with comment); pane shows approval state; events `approval.requested/decided`; rules can trigger on decisions; inbox notification "Approval requested".
**AC:** only the assignee (or project admin) can decide; agents can't decide.
**Size:** M

### S4.4.2: Recurring tasks
**Scope:** recurrence spec (daily/weekdays/weekly on days/monthly on day N or nth weekday/yearly/custom interval) + NL input ("every 2nd Monday"); on completion (or on schedule, per option) create the next instance with the same fields/subtasks; job for schedule-based recurrence.
**Size:** M
