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

### S4.1.2: Actions library
**Scope:** set field, assign, move section, add to project, remove from project, add tag, add comment, create subtasks (from list), mark complete, set due relative ("+3 days"), notify user (inbox), Slack message (enabled in P7), AI step (S4.1.5).
**Size:** M

### S4.1.3: Rule builder UI and run history
**Scope:** project "Rules" (⋯ → Rules): list with toggles, builder (trigger → conditions → actions with pickers), readable sentence preview, run history with status and errors, test-run on a chosen task (dry-run).
**Size:** L

### S4.1.4: NL → rule
**Scope:** `POST /ai/rules/compile` → rule JSON (validated) + readable sentence; ambiguous references ask back; saved with `created_from_prompt`.
**AC:** 20 fixture phrases → correct JSON (≥ 90% exact, rest ask for clarification rather than guess).
**Size:** M

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
