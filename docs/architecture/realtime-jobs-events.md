# Realtime, Jobs, and Events

## 1. The outbox pattern

Every service mutation writes, **in the same transaction**:
1. the domain change,
2. `activity` row(s),
3. `events_outbox` row(s).

After commit, the service calls `pg_notify('momentum_events', outbox_id)` (skipped in dry-run mode).

A **dispatcher** (a Procrastinate periodic task every 2s plus a NOTIFY-triggered wake-up) reads undispatched outbox rows in order and:
- fans out to the **WS hub** (via NOTIFY, already sent),
- enqueues jobs for **rules** (Phase 4), **notifications** (Phase 2), **embeddings** (Phase 3), **agent event triggers** (Phase 5), and **integrations** (Phase 7),
- marks `dispatched_at`.

Dispatch is **at-least-once**, so consumers must be idempotent (key: `outbox_id` + consumer name, stored in `consumer_offsets(consumer, last_outbox_id)` or a per-job dedupe key).

## 2. Event catalog

Event payloads share an envelope:

```json
{
  "id": 12345, "type": "task.updated", "workspace_id": "…",
  "entity_type": "task", "entity_id": "…",
  "actor": {"id": "…", "kind": "user|agent|rule|system|integration|import"},
  "activity_id": "…", "batch_id": null,
  "channels": ["project:<id>", "task:<id>", "user:<assignee_id>"],
  "data": { "changes": {"due_on": ["2026-09-20", "2026-09-27"]}, "version": 8 },
  "ts": "2026-09-23T10:00:00Z"
}
```

| Type | Phase | `data` |
|---|---|---|
| `task.created` | 1 | task summary, project/section placements |
| `task.updated` | 1 | `changes`, `version` |
| `task.completed` / `task.uncompleted` | 1 | `completed_by` |
| `task.deleted` / `task.restored` | 1 | |
| `task.moved` | 1 | project_id, from/to section, position |
| `task.added_to_project` / `task.removed_from_project` | 2 | project_id, section_id |
| `task.assigned` | 1 | old/new assignee |
| `task.dependency_added` / `task.dependency_removed` | 2 | depends_on_id |
| `subtask.reordered` | 1 | parent_id |
| `section.created` / `section.updated` / `section.moved` / `section.deleted` | 1 | |
| `project.created` / `project.updated` / `project.archived` / `project.deleted` | 1 | |
| `project.member_added` / `project.member_removed` | 1 | user_id, role |
| `comment.created` / `comment.updated` / `comment.deleted` | 1 | comment summary, mentions |
| `reaction.added` / `reaction.removed` | 1 | |
| `field_value.changed` | 2 | field_id, old/new |
| `attachment.added` / `attachment.deleted` | 2 | |
| `status_update.created` | 3 | status |
| `ai_action.proposed` / `ai_action.applied` / `ai_action.rejected` / `ai_action.undone` | 3 | ai_action_id, summary |
| `approval.requested` / `approval.decided` | 4 | state |
| `form.submitted` | 4 | form_id, task_id |
| `rule.ran` | 4 | rule_id, status |
| `agent_run.started` / `agent_run.finished` | 5 | agent_id, status, cost |
| `notification.created` | 2 | notification summary (channel `user:<id>` only) |
| `import.progress` / `import.finished` | 2 | stats |

**Adding an event type** requires updating this table, `momentum/core/events.py` (`EventType` enum), and the frontend event handler map (`apps/web/src/lib/realtime/handlers.ts`).

## 3. WebSocket protocol (`/ws`)

- Auth: the same cookie as the API (Easy Auth covers the upgrade request). Unauthenticated connections are closed with code 4401.
- Client → server:
  - `{"type":"subscribe","channels":["project:<id>","task:<id>","user:me"]}`. The server checks `can(view)` per channel; denied channels come back in `{"type":"subscribe_denied","channels":[…]}`.
  - `{"type":"unsubscribe","channels":[…]}`
  - `{"type":"ping"}` every 25s → `{"type":"pong"}`
- Server → client: `{"type":"event","event":{…envelope…}}`, plus `{"type":"resync"}` when the server detects a gap (client must refetch the active queries).
- Each event carries `id` (outbox id). The client tracks the last seen id per connection and requests `{"type":"replay","since":<id>}` on reconnect (the server replays up to 500 events from the outbox; beyond that it sends `resync`).
- Reconnect: exponential backoff 1s → 30s with jitter. On reconnect the client re-subscribes and replays.
- Multi-instance: each instance `LISTEN`s on `momentum_events` and loads the outbox row by id, so sticky sessions aren't needed.

## 4. Frontend handling

`handlers.ts` maps event types to TanStack Query cache updates:
- Entity events patch the cached entity when `version` is newer, otherwise ignore.
- Collection-affecting events (created/moved/deleted) invalidate the relevant list queries (`['project', id, 'tasks']`).
- Events whose `actor.id` is the current user and that were optimistically applied are reconciled (not double-applied) using `activity_id`.

## 5. Jobs (Procrastinate)

| Queue (prefixed `momentum_` in code) | Jobs | Concurrency |
|---|---|---|
| `default` | outbox dispatch, notifications, emails/Slack sends | 4 |
| `ai` | embeddings, summaries, agent runs, AI rule steps | 2 (protects gateway rate limits) |
| `integrations` | Slack events, Graph calendar sync, import jobs | 2 |
| `maintenance` | purge idempotency keys, expire ai_actions, recurring task generation, digest scheduling | 1 |

Rules:
- Jobs take **ids, not objects**, and reload state. They must be idempotent.
- Retries: exponential backoff, max 5 (AI: 3). Failures are logged with `request_id`/`job_id`, and permanent failures surface in the admin "Background jobs" panel (Phase 8).
- Periodic tasks (cron) are defined in `momentum/jobs/schedule.py` and deduplicated by Procrastinate's `queueing_lock`, so they're safe with several instances.
- `WORKER_MODE=embedded` starts the worker inside the web process lifespan. `separate` runs `momentum worker`.
