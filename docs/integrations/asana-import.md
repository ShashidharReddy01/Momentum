# Asana → Momentum Import Specification

Spec for slice **S2.7.1** (Asana importer). It is based on Asana's public REST API data model (`https://app.asana.com/api/1.0`). Asana identifies every object by a string `gid`. We keep every source `gid` in `external_links` (provider `asana`), so imports are **idempotent**: a re-run updates rows instead of duplicating them.

> Verify field names against the live API during the Phase 2 kickoff. Asana adds fields over time, and a recorded synthetic fixture of real responses is the test oracle.

## 1. How data leaves Asana

| Method | Coverage | Use |
|---|---|---|
| **REST API with a Personal Access Token** (recommended) | Everything the token owner can see: teams, projects, sections, tasks, subtasks, custom fields, tags, stories (comments), attachments metadata, dependencies, status updates, portfolios, goals | Primary importer path |
| Project JSON export (Project menu → Export → JSON) | One project's tasks, comments, and custom fields | Fallback for a single project; the importer accepts the file |
| Project CSV export | Flat task list, no comments or dependencies | Fallback via the CSV importer (S2.7.2) |
| Admin organization export (Enterprise) | Whole org | If the admin can provide it |

**Not available via the API** (must be recreated by hand or with Momentum's NL rule builder): rules/automations, forms (definitions), bundles, workflow builder settings, workload capacity settings, and saved report/dashboard layouts.

API practicalities: pagination `limit=100` + `offset` token; `opt_fields` to pick fields; rate limit ~1,500 req/min on paid plans (150 on free), with 429 + `Retry-After` handled by backoff; attachment `download_url`s are short-lived (fetch immediately).

## 2. Object mapping

| Asana object | Key Asana fields | Momentum target | Notes |
|---|---|---|---|
| Workspace / Organization | `gid, name, is_organization` | `workspaces` (existing) | Import into the current workspace |
| User | `gid, name, email, photo` | `users` (match by **email**) | Unmatched users become `status=invited` placeholders (or are mapped to someone via the import UI) |
| Team | `gid, name, description, organization` | `teams` | Members via `GET /teams/{gid}/users` → `team_members` |
| Project | `gid, name, archived, color, notes/html_notes, owner, team, members, privacy_setting, default_view, start_on, due_on, created_at, current_status_update, custom_field_settings, completed` | `projects` + `project_members` | `privacy_setting`: `public_to_workspace`/`private_to_team` → `team`, `private` → `private`; `default_view`: list/board/calendar/timeline map 1:1; `archived` → `archived_at`; Asana color names → nearest `--proj-n` token |
| Section | `gid, name, project, created_at` | `sections` | Keep Asana order (API returns sections in order) → fractional keys |
| Task | see §3 | `tasks` + `task_projects` | Order within a section follows the API order of `GET /sections/{gid}/tasks` |
| Subtask | task with `parent` | `tasks.parent_id` | Recursive (`GET /tasks/{gid}/subtasks`) |
| Dependency | `dependencies`, `dependents` | `task_dependencies` | Second pass after all tasks exist |
| Tag | `gid, name, color` | `tags` + `task_tags` | |
| Custom field | `gid, name, resource_subtype, enum_options[{gid,name,color,enabled}], precision, format, currency_code` | `field_defs` + `project_fields` | Type map in §4 |
| Custom field value | task `custom_fields[]` | `field_values` | Map enum option gids → our option ids |
| Story (comment) | `gid, created_at, created_by, resource_subtype=comment_added, text, html_text, is_pinned, likes` | `comments` (`created_via=import`, original author and timestamp preserved) | System stories (e.g., "assigned to", "changed due date") → optional **activity** rows marked `import`, off by default |
| Like / heart | `likes[]` on tasks and stories | `reactions` (👍) | |
| Attachment | `gid, name, host, download_url, view_url, size, created_at, parent` | `attachments` | `host=asana` → download and store (optional, default on for files < 50 MB); external hosts (gdrive, dropbox, box, onedrive) → link-only attachment |
| Status update | `status_type (on_track, at_risk, off_track, on_hold, complete), title, text/html_text, author, created_at, parent` | `status_updates` | Latest one sets `projects.status` |
| Portfolio (Phase 6) | `gid, name, owner, items` | `portfolios` + `portfolio_items` | If Phase 6 is live, else skip with a note |
| Goal (Phase 6) | `gid, name, owner, time_period, metric{current, target, initial, unit}, status, parent goals` | `goals` + `goal_links` | Same |
| Follower | task `followers[]` | `followers` | |
| Assignee status / My Tasks sections | `assignee_section` (per user) | `my_task_placements` | Best effort, since only the token owner's own My Tasks is readable |

## 3. Task field mapping

| Asana | Momentum | Rule |
|---|---|---|
| `name` | `title` | Truncate to 500 chars (full text into description if longer) |
| `html_notes` (fallback `notes`) | `description` (Tiptap JSON) + `description_text` | HTML → Tiptap converter: `<strong>`, `<em>`, `<u>`, `<s>`, `<code>`, `<a>`, `<ul>/<ol>/<li>`, `<h1>/<h2>`, `<hr>`, `<blockquote>`, `<pre>`; `<a data-asana-gid>` mentions → mention nodes when the target was imported, else a link |
| `resource_subtype` | `type` | `default_task`→`task`, `milestone`→`milestone`, `approval`→`approval`; `section` (legacy) → skipped |
| `approval_status` | `approval_state` | pending, approved, rejected, changes_requested map 1:1 |
| `assignee` | `assignee_id` | Via the user map |
| `start_on` / `start_at` | `start_on` | Date part |
| `due_on` / `due_at` | `due_on` / `due_at` | Keep timezone-aware `due_at` |
| `completed`, `completed_at`, `completed_by` | `completed_at`, `completed_by` | |
| `created_at`, `created_by` | `created_at`, `created_by` | Preserve original timestamps; `created_via=import` |
| `memberships[{project, section}]` | `task_projects` rows | **Multi-homing is preserved** (one row per project) |
| `parent` | `parent_id` | |
| `tags[]`, `followers[]`, `dependencies[]` | see §2 | |
| `num_likes`/`likes` | `reactions` | |
| `permalink_url` | `external_links.url` | Shown as "Open in Asana" during transition |
| `custom_fields[]` | `field_values` | §4 |
| Task number | `tasks.number` | New `T-n` numbers are allocated; the Asana gid stays searchable via external_links |

## 4. Custom field type mapping

| Asana `resource_subtype` | Momentum `field_defs.type` | Value mapping |
|---|---|---|
| `text` | `text` | `text_value` |
| `number` (with `format=currency`) | `currency` | `number_value`, `currency_code` into options |
| `number` (with `format=percentage`) | `percent` | `number_value` |
| `number` (other) | `number` | `number_value`, `precision` |
| `enum` | `single_select` | `enum_value.gid` → our option id (colors mapped, disabled → archived) |
| `multi_enum` | `multi_select` | `multi_enum_values[]` |
| `date` | `date` | `date_value.date` (or `date_time`) |
| `people` | `people` | `people_value[]` via the user map |
| `formula`, `custom_id`, `time tracking` (`estimated_time`/`actual_time`), `rollup`-style fields | `text` snapshot (read-only note) | Stored as their `display_value` text; `estimated_time` also sets `tasks.estimate_minutes` |

Asana's library/global fields become `field_defs.is_library=true`.

## 5. Import algorithm (idempotent, resumable)

1. **Discover**: user supplies a PAT (never stored) → list workspaces → pick teams/projects → preview counts.
2. **Pass 1, structure**: users (map/confirm), teams, projects, sections, custom field defs, tags. Upsert by `external_links(asana, gid)`.
3. **Pass 2, tasks**: per section, page tasks with `opt_fields` for all §3 fields; upsert tasks, placements, field values, followers; recurse into subtasks.
4. **Pass 3, relations**: dependencies, multi-homing memberships to projects imported later, mentions inside descriptions.
5. **Pass 4, conversation**: stories (comments; optional system activity), likes, attachments (download queue).
6. **Pass 5, status**: status updates, portfolios and goals (if the phase is live).
7. **Finish**: recompute counters, rebuild search vectors, enqueue embeddings, write the `import_jobs` summary (counts per type, skipped items with reasons) and emit `import.finished`.

Each pass checkpoints progress in `import_jobs.log`, so a failed import resumes from the last completed page.

## 6. Validation after import

- Count reconciliation per project: tasks (open/completed), subtasks, comments, attachments.
- Spot-check screen: 10 random tasks shown side by side (Asana fields vs Momentum fields).
- A list of unmapped users and skipped objects (rules, forms) with a checklist for manual recreation.

## 7. What changes for users

| In Asana | In Momentum |
|---|---|
| Rules | Recreate with plain-English rules (Phase 4). The import report lists the projects that had rules (visible from project settings only, so the owner confirms) |
| Forms | Recreate with the form builder or conversational intake (Phase 4) |
| Task links `app.asana.com/...` in text | Rewritten to Momentum task links when the target was imported |
