# Data Model

All tables live in the Postgres schema configured by `MOMENTUM_DB_SCHEMA` (default `momentum`). Alembic's version table is `momentum.alembic_version`.

## 0. Conventions

| Convention | Rule |
|---|---|
| Primary keys | `id uuid` generated in the app as **UUIDv7** (time-ordered) |
| Tenancy | Every top-level table has `workspace_id uuid not null` + an index. Child tables may omit it when always joined through a parent that has it, but tasks, comments, activity, and events all carry it. |
| Timestamps | `created_at timestamptz not null default now()`, `updated_at timestamptz not null default now()` (service-maintained) |
| Soft delete | `deleted_at timestamptz null` on user-facing entities (projects, sections, tasks, comments, attachments, fields, rules, forms, templates, goals). Default queries filter `deleted_at is null`. |
| Concurrency | `version int not null default 1` on tasks, projects, sections, rules, agents. Incremented on every update. |
| Ordering | `position text collate "C"` fractional index keys (ADR-0007) |
| Rich text | Stored as Tiptap/ProseMirror JSON (`jsonb`), plus a derived `*_text text` column for search and AI |
| Enums | Postgres `text` + `CHECK` constraint (easier migrations than native enums) |
| Provenance | `created_by uuid` (user or agent user), `created_via text` in (`ui`,`ai`,`agent`,`rule`,`import`,`integration`,`api`,`mcp`) |
| JSON | `jsonb`, validated by Pydantic in services |
| FKs | `on delete restrict` by default; `cascade` only for pure child rows (e.g., `task_tags`) |

## 1. Identity and tenancy

### `workspaces`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| name | text not null | |
| slug | text unique not null | |
| settings | jsonb not null default '{}' | Workspace-level prefs (AI enabled, default timezone, week start) |
| task_seq | bigint not null default 0 | Counter for human task numbers |

### `users`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| workspace_id | uuid fk | |
| email | citext not null | Unique per workspace; lower-cased |
| name | text not null | |
| avatar_url | text null | |
| role | text check in (`admin`,`member`,`guest`) | Workspace role |
| status | text check in (`active`,`invited`,`disabled`) | |
| is_agent | bool not null default false | Agent accounts (S5.1.1: one per agent, email `<key>@agents.momentum.invalid`, never signs in, never a team member or project admin) |
| agent_id | uuid null fk agents | Set when `is_agent` |
| timezone | text not null default 'UTC' | IANA |
| prefs | jsonb not null default '{}' | Notification prefs, default views, shortcuts. Per-project list views (`ProjectViewPrefs`): assignees, tags, due, show_completed, sort and group (S7.4.1: also `field:<field id>`), `fields` (up to 10 custom-field filters, `<field id>:<op>[:<arg>]`, `domain/fields/filters.py`), and the last tab |
| last_seen_at | timestamptz null | |
| Unique | (workspace_id, email) | |

### `user_identities`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| user_id | uuid fk users | |
| provider | text | `dev`, `easyauth-aad`, `oidc:<issuer>`, `host` |
| tenant_id | text null | Entra `tid` |
| subject | text not null | Entra `oid` / OIDC `sub` |
| email_at_link | citext | |
| last_login_at | timestamptz | |
| Unique | (provider, tenant_id, subject) | |

### `api_tokens`
id, workspace_id, user_id, name, `token_hash` (sha256), `prefix` (first 8 chars for display), scopes text[], last_used_at, expires_at, revoked_at.
**As built (S5.1.6, no migration; the table existed since 0001):** secrets are `mtm_` + 43 url-safe characters, stored only as a sha256 hash; `prefix` is the first 10 characters (`mtm_` + 6). `user_id` is a person, or an agent's account (issued by an admin). Scopes: `read`, `tasks:write`, `attachments:write`, `ai`, `admin`. Expiry is required (1–365 days, default 90). `last_used_at` is refreshed at most once a minute.

## 2. Organization

### `teams`
id, workspace_id, name (≤120), description, color (token `proj-1`…`proj-12`), created_by, version, timestamps, deleted_at.

### `team_members`
team_id, user_id, role check in (`lead`,`member`), pk (team_id, user_id).

### `projects`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| workspace_id, team_id | uuid fk | |
| name | text not null | |
| color, icon | text | Token names, not hex |
| privacy | text check in (`team`,`private`) | `team` = visible to team members (and admins) |
| owner_id | uuid fk users | |
| default_view | text check in (`list`,`board`,`calendar`,`timeline`,`overview`,`dashboard`) | |
| brief | jsonb null, brief_text text | Overview brief |
| status | text check in (`on_track`,`at_risk`,`off_track`,`on_hold`,`complete`) null | Latest status (denormalized from status_updates) |
| start_on, due_on | date null | Editable since S6.2.1 (overview; editors; activity + undo; start ≤ due) |
| archived_at | timestamptz null | |
| is_template | bool default false | |
| version, created_by, created_via, timestamps, deleted_at | | |

### `project_members`
project_id, user_id, role check in (`admin`,`editor`,`commenter`,`viewer`), pk (project_id, user_id).

### `favorites`
user_id, entity_type (`project`,`portfolio`,`goal`,`dashboard`), entity_id, position (fractional key, `COLLATE "C"`), created_at. pk (user_id, entity_type, entity_id). Index (user_id, position).

### `sections`
id, workspace_id, project_id, name, position, version, timestamps, deleted_at. Index (project_id, position).

## 3. Tasks

### `tasks`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| workspace_id | uuid fk | |
| number | bigint not null | Human key `T-<number>`, unique per workspace (from `workspaces.task_seq`) |
| title | text not null | ≤ 500 chars |
| description | jsonb null | Tiptap JSON |
| description_text | text null | Derived plain text |
| type | text check in (`task`,`milestone`,`approval`) default `task` | |
| approval_state | text check in (`pending`,`approved`,`changes_requested`,`rejected`) null | Only for `approval` |
| assignee_id | uuid null fk users | |
| start_on | date null | |
| due_on | date null | |
| due_at | timestamptz null | When a time is set (due_on also set). Stored in UTC; `due_at` without `due_on` derives `due_on` in the actor's timezone; clearing `due_on` clears `due_at` |
| completed_at | timestamptz null | |
| completed_by | uuid null | |
| parent_id | uuid null fk tasks | Subtask |
| parent_position | text null | Order among siblings |
| recurrence | jsonb null | Repeat rule: `{freq: daily\|weekly\|monthly\|yearly, interval 1–99, by_weekday? [0=Mon…6], workdays_only?, day_of_month? (1–31 or -1 for last, monthly only), week_of_month? (1–4 or -1, needs exactly one by_weekday, monthly only), mode? on_complete\|on_schedule (default on_complete), text?}`, validated by `domain/tasks/service._check_recurrence`. Written since S3.2.1 (quick add); **generates the next instance since S4.4.2** (`domain/tasks/recurrence.py`'s `next_occurrence` + `service.spawn_next_occurrence`) |
| recurrence_parent_id | uuid null fk tasks | S4.4.2: set on a task auto-created as another recurring task's next occurrence. Doubles as the idempotency guard — a task with a child never spawns a second one |
| estimate_minutes | int null | Effort (Phase 6 workload) |
| priority | text null | Convenience built-in (`urgent`,`high`,`medium`,`low`). Settable since S3.2.1 (create, `PATCH`, bulk, AI tools), undoable |
| search_tsv | tsvector | Generated from title + description_text (weighted) |
| version | int | |
| created_by, created_via | | |
| created_at, updated_at, deleted_at | | |

**Indexes:** (workspace_id, number) unique; (assignee_id, completed_at, due_on); (parent_id, parent_position); GIN(search_tsv); GIN(title gin_trgm_ops).

### `task_projects` (multi-homing)
task_id, project_id, section_id, position (fractional, `COLLATE "C"`), added_at, added_by. pk (task_id, project_id). Index (project_id, section_id, position). Completed tasks keep their position, so undoing a completion restores the exact place.

### `task_dependencies`
task_id (the blocked task), depends_on_id (the blocker), created_by, created_at. pk (task_id, depends_on_id). Check task_id <> depends_on_id. The service prevents cycles.

### `followers`
task_id, user_id, pk. (Assignee and creator are auto-followers.)

### `tags`, `task_tags`
tags: id, workspace_id, name (unique per workspace among live tags, case-insensitive: a deleted tag frees its name, migration 0041), color, deleted_at. task_tags: task_id, tag_id pk.

### `reactions`
id, workspace_id, entity_type (`task`,`comment`), entity_id, user_id, emoji. Unique (entity_type, entity_id, user_id, emoji).

### `my_task_placements` (Phase 1)
user_id, task_id, bucket (`recently_assigned`,`today`,`this_week`,`later`), position, pinned bool, updated_at. pk (user_id, task_id). `nudge_snoozed_until` date null (S5.3.4, migration 0030): the person snoozed Nudge's reminders on this task until that day (kickoff Q7).

## 4. Custom fields (Phase 2)

### `field_defs`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| workspace_id | uuid | |
| name | text | |
| type | text check in (`text`,`number`,`single_select`,`multi_select`,`date`,`people`,`checkbox`,`url`,`currency`,`percent`) | |
| options | jsonb | For selects: `[{id,label,color,archived}]`; number: `{precision, unit}` |
| description | text | |
| is_library | bool | Shared workspace field |
| created_by, timestamps, deleted_at | | |

### `project_fields`
project_id, field_id, position, is_visible, pk (project_id, field_id).

### `field_values`
task_id, field_id, `value jsonb` (typed by field type: string / number / option id / [option ids] / date / [user ids] / bool), updated_at, updated_by. pk (task_id, field_id). GIN(value) for filters.

## 5. Collaboration

### `comments`
id, workspace_id, task_id, author_id, body jsonb, body_text text, is_ai bool default false, edited_at, created_at, deleted_at, created_via. Index (task_id, created_at).

### `mentions`
id, workspace_id, source_type (`comment`,`task_description`), source_id, target_type (`user`,`task`,`project`), target_id. Used for notifications and backlinks.

### `attachments`
id, workspace_id, task_id null, comment_id null, storage_key, filename, mime, size_bytes, sha256, text_extract text null, extract_status (`pending`,`done`,`skipped`,`failed`), uploaded_by, created_at, deleted_at.

### `status_updates`
id, workspace_id, entity_type (`project`,`portfolio`,`goal`), entity_id, status (as project.status), title, body jsonb, body_text, author_id, generated_by_ai bool, ai_action_id null, created_at.
**As built (S3.4.3, migration 0020):** plus `created_via` and `deleted_at` (an undone update is withdrawn, not erased); `body` = `{summary, sections: {completed, slipped, blockers, next: [{text}]}}`; `body_text` a plain rendering ("At risk: title", summary, "Slipped:" + "- item" lines); index (entity_type, entity_id, created_at). Posting sets `projects.status` and bumps the project's version in the same transaction; undo (`status_updates.withdraw`) restores the previous status unless it changed since. `[T-n]` keys in the text are resolved for each reader when listed.

## 6. Activity, events, notifications

### `activity`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| workspace_id | uuid | |
| actor_id | uuid null | User or agent user; null = system |
| actor_kind | text check in (`user`,`agent`,`rule`,`system`,`integration`,`import`) | |
| entity_type | text | `task`, `project`, `section`, `comment`, … |
| entity_id | uuid | |
| verb | text | e.g., `task.updated`, `task.completed` |
| diff | jsonb | `{field: [old, new]}` |
| undo_payload | jsonb null | Service-specific inverse operation; null = not undoable |
| undone_at | timestamptz null | |
| batch_id | uuid null | Groups multiple rows (bulk edits, AI action) for batch undo |
| ai_action_id | uuid null | |
| request_id | text | Correlation |
| created_at | timestamptz | |

Index (entity_type, entity_id, created_at desc), (workspace_id, created_at desc), (batch_id).

### `events_outbox`
id bigserial pk, workspace_id, type text, entity_type, entity_id, payload jsonb, activity_id uuid null, created_at, dispatched_at null. Index (dispatched_at) where dispatched_at is null.

### `consumer_offsets` (Phase 2)
consumer text pk, last_outbox_id bigint, updated_at. Tracks outbox consumers for idempotent dispatch.

### `notifications`
id, workspace_id, user_id, kind (`assigned`,`mentioned`,`commented`,`completed`,`due_soon`,`overdue`,`rule`,`approval_requested`,`approval_decided`,`agent_proposal`,`digest`), entity_type, entity_id, activity_id null, title, snippet, priority_score real, read_at, archived_at, created_at. Index (user_id, archived_at, created_at desc). `rule` added in migration 0022 (S4.1.2's `notify_user` action); `agent_alert` added in migration 0028 (S5.1.1; an agent needs an admin's attention, produced from S5.1.2); `unblocked` added in migration 0031 (S6.1.3: "You're up", sent to a task's assignee when its last open blocker is completed; a per-kind preference like the others).

### `idempotency_keys`
key text, user_id, method, path, response_status, response_body jsonb, created_at. pk (user_id, key). Purged after 24h by a periodic job.

## 7. Workflow (Phase 4)

- `rules` (S4.1.1, migration 0021): id, workspace_id, project_id null (null = workspace rule), name, enabled, trigger jsonb, conditions jsonb, actions jsonb, created_from_prompt text null, version, created_by (the rule acts as this person, with their permissions), timestamps, deleted_at. The JSON shape is validated on write (`domain/rules/schemas.py`).
- `rule_runs` (S4.1.1): id, workspace_id, rule_id, project_id null, outbox_event_id, status (`success`,`skipped`,`failed`), depth int (of the triggering event), actions_run int, error text, started_at, finished_at, activity_batch_id. **Unique `(rule_id, outbox_event_id)`**: a rule never fires twice on one event. Skipped runs (depth or rate limit) are logged here.
- `rule_ai_steps` (S4.1.5, migration 0023): id, workspace_id, rule_id, rule_run_id null, project_id null, task_id, kind (`summarize_to_comment`,`classify_field`,`extract_fields`,`draft_reply`), field_id text null (`priority` or a custom field id, `classify_field` only), status (`queued`,`running`,`done`,`failed`), depth int (the depth the rule's own writes carry), result text null (what it wrote, for the run history), error text null, created_at, started_at, finished_at, activity_batch_id. Written by the `ai_step` action inside the rule run's savepoint and run afterwards on the `momentum_ai` queue (`momentum/ai/rule_steps.py`), because a model call must not be made inside the run's transaction. One attempt per step: a row left `running` for more than 15 minutes is failed, never retried.
- S4.1.2 added actions `set_field`, `add_to_project`, `remove_from_project`, `add_tag`, `create_subtasks`, `set_due_relative`, `notify_user` (`slack_message` still refused, P7) and the `task.due_approaching` trigger. No new table for the trigger: `momentum/jobs/due_approaching.py` (hourly, `momentum_maintenance` queue) scans for tasks due tomorrow and emits `task.due_approaching` through `domain/rules/due_scan.py`, deduped per (task, due date) by checking `events_outbox` for a prior event with the same `due_on` before emitting.
- `forms` (S4.2.1, migration 0024; `conversational` added S4.2.2, migration 0025): id, workspace_id, project_id, section_id null (falls back to the project's default section, like task creation), name, description text null, questions jsonb (list of `{id, label, help_text?, required, maps_to, show_if?}` — `maps_to` is `title`/`description`/`assignee`/`due_on`/`priority` or a custom field id; `show_if` is branching v1: `{question_id, equals}`, and must name an earlier question), enabled bool, public_enabled bool, conversational bool (S4.2.2: the same questions asked through a chat instead of a plain form), public_token text unique (generated once, kept even while the public link is off), version, created_by, timestamps, deleted_at. Validated on write by `domain/forms/schemas.py`: exactly one required, unconditional `title` question; each target used at most once; a people-type custom field can't be a target.
- `form_submissions` (S4.2.1): id, workspace_id, form_id, task_id, answers jsonb (the raw submitted values, keyed by question id), submitted_by null (the logged-in submitter on the internal link; always null on the public link), ip_hash text null (salted hash of the public submitter's IP — never stored raw — used only to throttle spam), created_at. A submission always creates the task as the **form's owner** through `domain/tasks/service.create_task` (one write path), never as the submitter: the public link has no session to build a real actor from, and the internal link stays consistent with it. `form.submitted` is a rules trigger (optionally scoped to one form via `form_id`); the executor widens for it by adding a second outbox event (`entity_type="task"`, alongside the ordinary `task.created`) so `domain/rules/engine.py`'s task-only event filter still applies. **No table for in-progress conversations** (S4.2.2): `POST /forms/{id}/converse` is stateless — the client resends the whole transcript each turn and the model recomputes its best-guess answers — so a conversational submission is `submit_form` (the same one write path) plus a comment on the created task holding the transcript (`domain/forms/service.attach_transcript`), not a second kind of submission row.
- `templates` (S4.3.1, migration 0026): id, workspace_id, project_id null (null for a `kind="project"` template — workspace-wide, reusable from any project; set for a `kind="task"` template, S4.3.2's per-project ones), kind (`project`,`task`), name, description, payload jsonb, created_by, timestamps, deleted_at. A `project` payload: `{roles: [{id, label}], fields: [field_id], sections: [{name, tasks: [{title, description, priority, due_offset_days, start_offset_days, role_id, field_values: {field_id: value}, subtasks: [...same shape]}]}], rules: [{name, enabled, trigger, conditions, actions}]}` — dates are offsets in days from the earliest date among the captured project's own tasks (day 0 if it had none); assignees become `role_id`s (one per distinct person found, labelled by their name at save time) instead of user ids, and a rule's `user_id`/`to_section` references are captured as `role_id`/`section_index` the same way, so nothing in a template depends on the source project's specific people or section ids. "New from template" (`service.create_project_from_template`) picks a start date and maps roles to real people, then replays the payload through the same services every other caller uses — `create_project`, `create_task`/`create_subtask`/`update_task`, `attach_field`/`set_task_field_value`, `create_rule` — so a template-created project is indistinguishable from a hand-built one. A rule or field reference that no longer resolves at instantiation time (deleted since the template was saved) is silently skipped rather than failing the whole project. A `task` payload (S4.3.2) is much simpler and authored directly rather than captured: `{title, description, subtasks: [title], field_values: {field_id: value}}`; `service.create_task_from_template` replays it with an optional title override, section and assignee/due date.

## 8. Planning (Phase 6)

- `portfolios` (**as built, S6.2.2, migration 0032**): id, workspace_id, name, description, owner_id, status null (latest check-in, denormalized like `projects.status`, same values), version, timestamps, deleted_at. Visible to every workspace member; the owner and workspace admins edit. `portfolio_items`: portfolio_id + project_id (pk), workspace_id, position (fractional key, `COLLATE "C"`), created_at. Check-ins are `status_updates` rows with `entity_type='portfolio'`. A portfolio's project rows are computed per viewer (projects they can't see are only counted).
- `goals` (**as built, S6.3.1, migration 0033**): id, workspace_id, parent_id null (sub-goals, ≤ 4 levels, no cycles), name, description, owner_id (a person), period_start/period_end (dates, start ≤ end) + period_label ("Q4 2026"), metric jsonb null (`{type: number|percent|currency, start, target, current, unit}`; a target below the start works), progress_source (`manual`,`projects`,`subgoals`), status null (latest check-in), version, timestamps, deleted_at. `goal_links`: goal_id + entity_type (`project`,`portfolio`) + entity_id (pk), workspace_id, created_at. Progress is never stored: it's computed per viewer (metric position; average completion of linked projects and linked portfolios' projects they can see; average of sub-goals), null when there's nothing to go on. Check-ins are `status_updates` with `entity_type='goal'` and can move `metric.current`.
- `capacity` (**as built, S6.4.1, migration 0034**): user_id + week_start (pk; a Monday), workspace_id, capacity_minutes (0–6000), updated_at. One person's capacity for one week (time off, a short week), overriding their usual hours in `users.prefs['weekly_hours']` (hours, null = default) and the workspace default in `workspaces.settings['workload']['default_hours']` (else `MOMENTUM_WORKLOAD_DEFAULT_HOURS`). `tasks.estimate_minutes` (existing column) is now editable end to end: the effort the workload view spreads over a task's working days.
- `capacity`: user_id, week_start date, capacity_minutes int. Default from user prefs.
- `dashboards` (**as built, S6.5.1, migration 0036**): id, workspace_id, owner_id, name, description, scope (`project`,`workspace`), project_id null (set exactly when scope = `project`; **one live dashboard per project**, a partial unique index), version, timestamps, deleted_at. No `layout` column: widget order is `dashboard_widgets.position` and each widget's width is in its `viz`. A workspace dashboard is visible to every member, edited by its owner or an admin; a project dashboard follows the project (whoever can see it; editors and admins edit). Deleting a project's dashboard returns its tab to the starter layout. `dashboard_widgets`: id, workspace_id, dashboard_id, kind (`count`,`bar`,`line`,`donut`,`list`), title, query_spec jsonb (`QuerySpec` v1 in `domain/dashboards/schemas.py`, stored without defaults, validated against the kind on every write), viz jsonb (`{size: sm|md|lg}`), position (fractional key, `COLLATE "C"`), version, created_by, timestamps, deleted_at. **Numbers are never stored**: every read runs the spec as the viewer (`domain/dashboards/query.py`). **S6.5.2, migration 0037:** `created_from_prompt` text null: the question Mo drafted the chart from (the card shows the amber ✦ with it).
- **Template payload `dependencies` (S6.1.3, no migration):** a `project` template's payload gains `dependencies: [{task: [section index, task index], blocked_by: [section index, task index]}]` between top-level tasks, captured by "Save as template" and by the AI drafter (`template_from_brief/v2`'s `after` titles), replayed through `add_dependency` after the tasks exist; older payloads without the key still work.
- `forecasts` (**as built, S6.5.3, migration 0038**): id, workspace_id, project_id, computed_at, as_of date, status (`ok`,`done`,`no_history`,`growing`: work arrives at least as fast as it is finished, so no end date; migration 0039), p50/p80/p95 date null (only when `ok`), risk_score real (0–100), risk_level (`none`,`low`,`medium`,`high`), drivers jsonb (`[{kind, text, points, tasks}]` strongest first: Radar's signals + the forecast against the due date), inputs jsonb (`{mode: tasks|hours, remaining, remaining_tasks, weeks, throughput[], added[], chain_days, runs}`). One row per computation (nightly or a refresh); the newest is current. Computed data: no activity or undo; a new row emits `project.forecast_updated`. Index (project_id, computed_at).

## 9. AI and agents (Phases 3, 5)

### `ai_conversations`, `ai_messages`
- conversations: id, workspace_id, user_id, context_type (`global`,`task`,`project`), context_id null, title, created_at, updated_at.
- messages: id, conversation_id, role (`user`,`assistant`,`tool`), content jsonb (text parts, tool calls, citations), tokens_in, tokens_out, llm_call_id, created_at.
- **As built (S3.3.1, migration 0019):** both carry `workspace_id`. Conversations: `context_type` in (`global`,`task`,`project`) set from the screen the chat started on (only if the user can see it), `title` = the first question (80 chars), index (user_id, updated_at). Messages: `role` in (`user`,`assistant`) only (tool traffic is not stored: it is re-derivable and could hold content the user later loses access to); `content` = `{text}` for the user, `{text, steps[{name, ok, summary, preview}], citations[{ref, type, valid, id, key, title}], action_id, candidates, grounded, retrieved}` for Mo; `tokens_in/out` = the turn's totals over all its model calls (so `llm_call_id` stays null: a turn makes several `llm_calls` rows, written in their own transaction); `ON DELETE CASCADE` from the conversation; index (conversation_id, created_at). Private to the owner. They record **no `activity`/outbox rows** (personal records like AI prefs, the same choice as `ai_actions`); changes Mo proposes are audited when applied.

### `ai_actions`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| workspace_id | uuid | |
| source | text (`chat`,`command`,`inline`,`agent`,`rule`) | |
| source_id | uuid | conversation / agent_run / rule_run |
| proposed_for | uuid | User who must approve |
| summary | text | One-line human description |
| operations | jsonb | `[{tool, args, preview_diff}]` |
| risk | text (`low`,`medium`,`high`) | Max of operations |
| state | text (`proposed`,`approved`,`applied`,`rejected`,`expired`,`undone`,`failed`) | |
| decided_by, decided_at | | |
| applied_batch_id | uuid null | activity batch for undo |
| error | text null | |
| created_at, expires_at | | |

**As built (S3.1.3, migration 0016):** each operation is `{tool, args, summary, risk, diff, watch}`: `diff` is the registry's `DiffRow` list from the dry run, `watch` is `[{type: task|project, id, version}]` for every existing entity the operation changes (the stale check). `source_id` has no FK (its targets arrive with chat/agents). Indexes: `(proposed_for, state)`, and `expires_at` where `state = 'proposed'` (the expiry job). Applied operations' activity rows carry `ai_action_id`. `approved` is reserved for agent `confirm` flows (Phase 5); a human apply goes straight from `proposed` to `applied`.

**Workspace AI policy (`workspaces.settings['ai']`, S3.5.2):** `enabled`, `monthly_budget_usd`, `allow_auto_apply`, and since S5.1.4 `allow_medium_auto` (null = off).

**Workspace timezone (S5.1.2):** `workspaces.settings['timezone']` (IANA name, default `UTC`; `GET/PUT /workspace/settings`, admins) is the zone agent schedules with `timezone: workspace` use. No migration: `settings` is the existing JSONB.

### `agents`
id, workspace_id, user_id (agent account), key (e.g., `daily_digest`), name, avatar, description, instructions text, tools text[], scope jsonb (`{projects:[..], teams:[..]}`), autonomy (`suggest`,`confirm`,`auto`), triggers jsonb (`[{type: schedule, cron}, {type: event, event: task.created, filter}, {type: assigned}, {type: mentioned}]`), model_alias, budget_monthly_usd numeric, enabled, version, created_by, timestamps.

**As built (S5.1.1, migration 0028):** `user_id` unique FK (the agent's own account; `users.agent_id` points back, FK added in 0028); `key` varchar(60), unique per workspace; `name` varchar(80); `avatar` varchar(40) (an avatar key, not a URL); `kind` (`llm`,`handler`) + `handler` varchar(120) (set iff `kind='handler'`, a host-registered function, ADR-0009); `tools` text[]; `scope` jsonb `{projects: "member_of" | [ids], teams: [ids] | null}` (narrows, never grants); `triggers` jsonb (`schedule {cron, timezone: workspace|user|IANA}`, `event {event, filter {project_ids}}`, `assigned`, `mentioned`, `manual`); `model_alias` (`fast`,`default`,`smart`); `budget_monthly_usd` numeric(10,2); **`budget_monthly_tokens` bigint** (kickoff Q4: the cap while the agent's model is unpriced); `limits` jsonb `{max_steps, timeout_s}` (null = the `MOMENTUM_AGENT_*` ceilings); `enabled` (default **false**); `enabled_at` (migration 0029, S5.1.2: when it was last switched on; triggers ignore older events); `source` (`starter`,`host`,`custom`); `installed_hash` (sha256 of the definition as last installed, null for custom agents: tells an admin's edits apart from an untouched row); `created_by` null (null = installed by the CLI). No soft delete: agents are disabled, never deleted. Validated by `domain/agents/schemas.AgentConfig`, the same schema the YAML definitions use.

### `agent_runs`
id, agent_id, workspace_id, trigger jsonb, status (`queued`,`running`,`succeeded`,`failed`,`cancelled`,`budget_exceeded`), steps int, input jsonb, output jsonb, trace jsonb (list of steps: thought summary, tool call, result digest), tokens_in, tokens_out, cost_usd, started_at, finished_at, error.
**As built (S5.1.1, migration 0028):** plus `dedupe_key` varchar(200) null, **unique per agent** `(agent_id, dedupe_key)` (the same trigger delivered twice runs once) and `created_at`; `cost_usd` numeric(12,6). Indexes (agent_id, created_at), (workspace_id, created_at). Written by the runtime (S5.1.2); `llm_calls.agent_run_id` now has its FK here (`ON DELETE SET NULL`).

### `llm_calls`
id, workspace_id, feature (`chat`,`command`,`summarize`,`status_draft`,`agent:<key>`,`embed`,…), alias (`fast`,`default`,`smart`,`embed`), model (as reported by the gateway), prompt_version null, user_id null (null for agents and system calls), agent_run_id null (FK added with `agent_runs` in Phase 5), tokens_in, tokens_out, cost_usd numeric(12,6), latency_ms, status (`ok`,`error`,`budget_exceeded`), error_code null (the failure kind: `timeout`,`connection`,`rate_limited`,`server_error`,`bad_request`,`auth`,`bad_response`), created_at. Index (workspace_id, created_at) for budgets and the usage page; index (user_id, created_at) for the per-person hourly limit (migration 0040, Phase 7). Written in its own transaction, so usage of a rolled-back request still counts. (No prompt bodies. Optional debug capture goes to a separate table behind a flag with a TTL.) Migration 0015 (S3.1.1).

### `ai_memory`
id, workspace_id, scope (`workspace`,`team`,`project`), scope_id, text, created_by, timestamps. Admin-editable facts injected into prompts.

**As built (S3.1.5, migration 0018):** plus `deleted_at` (soft delete, so removal is undoable); check `scope_id is null` exactly when `scope = 'workspace'`; index `(workspace_id, scope, scope_id)`. Text ≤ 300 characters, ≤ 50 bullets per scope. Edit rights: workspace → workspace admin; team → team lead or admin; project → project admin. Service `ai/memory.py` (activity with undo + `ai_memory.changed` event).

### `embeddings`
| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| workspace_id | uuid | |
| entity_type | text (`task`,`comment`,`attachment`,`project`,`status_update`) | |
| entity_id | uuid | |
| chunk_no | int | |
| content_hash | text | Skip re-embed if unchanged |
| text | text | The chunk (for citations and snippets) |
| model | text | e.g., alias → resolved model id |
| dim | int | 1024 |
| embedding | vector(1024) | |
| updated_at | timestamptz | |

Index: HNSW (`embedding vector_cosine_ops`), (entity_type, entity_id). Unique (entity_type, entity_id, chunk_no, model).

**As built (S3.1.4, migration 0017):** also indexed on `workspace_id`; `entity_type` check allows the five types above (`status_update` arrives with S3.4.3). `content_hash` = sha256(model + chunk text): an unchanged entity is never re-sent to the gateway. The column type is a local `vector(1024)` (`ai/vector.py`, no `pgvector` Python dependency). Rows are derived data: `momentum reindex` rebuilds them.

### `ai_summaries`
id, workspace_id, entity_type, entity_id, kind (`thread`,`project_week`,`inbox`,`task`), content_hash, summary text, model, created_at. Unique (entity_type, entity_id, kind, content_hash). A cache that is safe to purge. Created in S3.1.4 (migration 0017); filled from S3.4.1. **As used (S3.4.1):** `thread` rows are keyed `entity_type='task'` (the task), `inbox` rows `entity_type='user'` (the reader); `content_hash` = sha256 of prompt version + model + the exact content summarized; written with insert-on-conflict-do-nothing.

### `feedback`
id, workspace_id, user_id, target_type (`ai_message`,`ai_action`,`agent_run`), target_id, rating (+1/−1), comment, created_at.
**As built (S3.3.1, migration 0019):** unique (user_id, target_type, target_id): a second rating replaces the first. Only the owner of the conversation (messages) or the person an action was proposed for can rate it; `agent_run` arrives in Phase 5.

## 10. Integrations (Phase 9)

- `integration_accounts`: id, workspace_id, provider (`slack`,`graph`), external_workspace_id, config jsonb, secrets_ref (Key Vault/env reference, not the secret), installed_by, timestamps.
- `external_links`: id, workspace_id, entity_type, entity_id, provider, external_id, url, meta jsonb (e.g., Slack message permalink; Asana gid for imported rows).
- `import_jobs`: id, workspace_id, source (`asana`,`csv`), status, stats jsonb, log jsonb, started_by, timestamps.

## 11. Search strategy

- Keyword: `tasks.search_tsv`, `comments.body_text` (tsvector computed), trigram on titles for fuzzy `⌘K`.
- Semantic: `embeddings` (Cohere v3, `input_type=search_document` on write, `search_query` on read).
- Hybrid ranking: reciprocal rank fusion of keyword + vector results, then the permission filter is applied **in SQL** by joining visible projects/tasks for the principal.
