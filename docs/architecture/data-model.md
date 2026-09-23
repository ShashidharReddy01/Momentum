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
| is_agent | bool not null default false | Agent accounts |
| agent_id | uuid null fk agents | Set when `is_agent` |
| timezone | text not null default 'UTC' | IANA |
| prefs | jsonb not null default '{}' | Notification prefs, default views, shortcuts |
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
| start_on, due_on | date null | |
| archived_at | timestamptz null | |
| is_template | bool default false | |
| version, created_by, created_via, timestamps, deleted_at | | |

### `project_members`
project_id, user_id, role check in (`admin`,`editor`,`commenter`,`viewer`), pk (project_id, user_id).

### `favorites`
user_id, entity_type (`project`,`portfolio`,`goal`,`dashboard`), entity_id, position. pk (user_id, entity_type, entity_id).

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
| due_at | timestamptz null | When a time is set (due_on also set) |
| completed_at | timestamptz null | |
| completed_by | uuid null | |
| parent_id | uuid null fk tasks | Subtask |
| parent_position | text null | Order among siblings |
| recurrence | jsonb null | RRULE-like spec (Phase 4) |
| estimate_minutes | int null | Effort (Phase 6 workload) |
| priority | text null | Convenience built-in (`urgent`,`high`,`medium`,`low`) |
| search_tsv | tsvector | Generated from title + description_text (weighted) |
| version | int | |
| created_by, created_via | | |
| created_at, updated_at, deleted_at | | |

**Indexes:** (workspace_id, number) unique; (assignee_id, completed_at, due_on); (parent_id, parent_position); GIN(search_tsv); GIN(title gin_trgm_ops).

### `task_projects` (multi-homing)
task_id, project_id, section_id, position, added_at, added_by. pk (task_id, project_id). Index (project_id, section_id, position).

### `task_dependencies`
task_id (the blocked task), depends_on_id (the blocker), created_by, created_at. pk (task_id, depends_on_id). Check task_id <> depends_on_id. The service prevents cycles.

### `followers`
task_id, user_id, pk. (Assignee and creator are auto-followers.)

### `tags`, `task_tags`
tags: id, workspace_id, name (unique per workspace, case-insensitive), color. task_tags: task_id, tag_id pk.

### `reactions`
id, workspace_id, entity_type (`task`,`comment`), entity_id, user_id, emoji. Unique (entity_type, entity_id, user_id, emoji).

### `my_task_placements` (Phase 1)
user_id, task_id, bucket (`recently_assigned`,`today`,`this_week`,`later`), position, pinned bool, updated_at. pk (user_id, task_id).

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
id, workspace_id, user_id, kind (`assigned`,`mentioned`,`commented`,`completed`,`due_soon`,`overdue`,`approval_requested`,`approval_decided`,`agent_proposal`,`digest`), entity_type, entity_id, activity_id null, title, snippet, priority_score real, read_at, archived_at, created_at. Index (user_id, archived_at, created_at desc).

### `idempotency_keys`
key text, user_id, method, path, response_status, response_body jsonb, created_at. pk (user_id, key). Purged after 24h by a periodic job.

## 7. Workflow (Phase 4)

- `rules`: id, workspace_id, project_id null (null = workspace rule), name, enabled, trigger jsonb, conditions jsonb, actions jsonb, created_from_prompt text null, version, created_by, timestamps, deleted_at.
- `rule_runs`: id, rule_id, outbox_event_id, status (`success`,`skipped`,`failed`), depth int, error text, started_at, finished_at, activity_batch_id.
- `forms`: id, workspace_id, project_id, name, schema jsonb (fields, branching), conversational bool, public_token text unique null, is_active, created_by, timestamps, deleted_at.
- `form_submissions`: id, form_id, task_id, submitted_by null, answers jsonb, created_at.
- `templates`: id, workspace_id, kind (`project`,`task`), name, description, payload jsonb (sections, tasks with relative day offsets, roles, fields, rules), created_by, timestamps, deleted_at.

## 8. Planning (Phase 6)

- `portfolios`: id, workspace_id, name, owner_id, description, timestamps, deleted_at. `portfolio_items`: portfolio_id, project_id, position.
- `goals`: id, workspace_id, parent_id null, name, owner_id, period (`2026-Q4` / custom start/end), metric jsonb (`{type: number|percent|currency, start, target, current}`), progress_source (`manual`,`projects`,`subgoals`), status, timestamps, deleted_at. `goal_links`: goal_id, entity_type (`project`,`portfolio`), entity_id.
- `capacity`: user_id, week_start date, capacity_minutes int. Default from user prefs.
- `dashboards`: id, workspace_id, owner_id, name, scope (`project`,`workspace`), scope_id, layout jsonb. `dashboard_widgets`: id, dashboard_id, kind, query_spec jsonb, viz jsonb, position.
- `forecasts`: id, project_id, computed_at, p50 date, p80 date, p95 date, risk_score real, drivers jsonb.

## 9. AI and agents (Phases 3, 5)

### `ai_conversations`, `ai_messages`
- conversations: id, workspace_id, user_id, context_type (`global`,`task`,`project`), context_id null, title, created_at, updated_at.
- messages: id, conversation_id, role (`user`,`assistant`,`tool`), content jsonb (text parts, tool calls, citations), tokens_in, tokens_out, llm_call_id, created_at.

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

### `agents`
id, workspace_id, user_id (agent account), key (e.g., `daily_digest`), name, avatar, description, instructions text, tools text[], scope jsonb (`{projects:[..], teams:[..]}`), autonomy (`suggest`,`confirm`,`auto`), triggers jsonb (`[{type: schedule, cron}, {type: event, event: task.created, filter}, {type: assigned}, {type: mentioned}]`), model_alias, budget_monthly_usd numeric, enabled, version, created_by, timestamps.

### `agent_runs`
id, agent_id, workspace_id, trigger jsonb, status (`queued`,`running`,`succeeded`,`failed`,`cancelled`,`budget_exceeded`), steps int, input jsonb, output jsonb, trace jsonb (list of steps: thought summary, tool call, result digest), tokens_in, tokens_out, cost_usd, started_at, finished_at, error.

### `llm_calls`
id, workspace_id, feature (`chat`,`command`,`summarize`,`status_draft`,`agent:<key>`,`embed`,…), alias, model, user_id null, agent_run_id null, tokens_in, tokens_out, cost_usd, latency_ms, status, error_code, created_at. (No prompt bodies. Optional debug capture goes to a separate table behind a flag with a TTL.)

### `ai_memory`
id, workspace_id, scope (`workspace`,`team`,`project`), scope_id, text, created_by, timestamps. Admin-editable facts injected into prompts.

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

### `ai_summaries`
id, workspace_id, entity_type, entity_id, kind (`thread`,`project_week`,`inbox`), content_hash, summary text, model, created_at. Unique (entity_type, entity_id, kind, content_hash). A cache that is safe to purge.

### `feedback`
id, workspace_id, user_id, target_type (`ai_message`,`ai_action`,`agent_run`), target_id, rating (+1/−1), comment, created_at.

## 10. Integrations (Phase 7)

- `integration_accounts`: id, workspace_id, provider (`slack`,`graph`), external_workspace_id, config jsonb, secrets_ref (Key Vault/env reference, not the secret), installed_by, timestamps.
- `external_links`: id, workspace_id, entity_type, entity_id, provider, external_id, url, meta jsonb (e.g., Slack message permalink; Asana gid for imported rows).
- `import_jobs`: id, workspace_id, source (`asana`,`csv`), status, stats jsonb, log jsonb, started_by, timestamps.

## 11. Search strategy

- Keyword: `tasks.search_tsv`, `comments.body_text` (tsvector computed), trigram on titles for fuzzy `⌘K`.
- Semantic: `embeddings` (Cohere v3, `input_type=search_document` on write, `search_query` on read).
- Hybrid ranking: reciprocal rank fusion of keyword + vector results, then the permission filter is applied **in SQL** by joining visible projects/tasks for the principal.
