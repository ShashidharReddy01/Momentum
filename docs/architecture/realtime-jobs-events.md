# Realtime, Jobs, and Events

## 1. The outbox pattern

Every service mutation writes, **in the same transaction**:
1. the domain change,
2. `activity` row(s),
3. `events_outbox` row(s).

After commit, the service calls `pg_notify('momentum_events', outbox_id)` (skipped in dry-run mode).

**Realtime dispatch (S2.1.1, implemented):** each app process runs one background task
(`momentum/realtime/listener.py`) that `LISTEN`s on `momentum_events` and, on every
notification, calls `momentum/realtime/dispatch.py:dispatch_pending`, which re-reads every
outbox row above *that process's own* in-memory cursor (never filtered by `dispatched_at`,
because that flag is shared across processes and would make one process's read cause
another to skip rows — see the module docstring) and hands each one to that process's own
in-process `Hub` (`momentum/realtime/hub.py`), which fans it out to its own live websocket
connections. `dispatched_at` is still set (first writer wins) as a cross-process
"something saw this" marker for monitoring/pruning, not as a delivery lock.

**Job dispatch (Phase 2+, not yet built):** the same outbox additionally feeds
Procrastinate jobs for **rules** (Phase 4), **notifications** (Phase 2), **embeddings**
(Phase 3), **agent event triggers** (Phase 5), and **integrations** (Phase 7). Job
consumers are at-least-once and must be idempotent; each gets its own row in the generic
`consumer_offsets(consumer, last_event_id)` table (e.g. `consumer='notifications'`) —
the same table realtime uses per-connection (`consumer='ws:<user_id>'`), so this is one
cursor table for every kind of outbox consumer, not one table each.

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
| (channels for task events) | 1 | `task:<id>`, `project:<id>` of its placement, `user:<assignee>` |
| `task.moved` | 1 | `section_id`, `position` (bulk moves emit one per task, sharing the activity batch) |
| `task.added_to_project` / `task.removed_from_project` | 2 | project_id, section_id |
| `task.assigned` | 1 | `assignee_id`, `previous_assignee_id` (also sent to `user:<previous>`); emitted alongside `task.updated` |
| `task.dependency_added` / `task.dependency_removed` | 2 | depends_on_id |
| `subtask.reordered` | 1 | parent_id |
| `team.created` / `team.updated` / `team.deleted` / `team.restored` | 1 | `changes`, `version` (updated) |
| `team.member_added` / `team.member_updated` / `team.member_removed` | 1 | `user_id`, `role` (channels also `user:<id>`) |
| `section.created` / `section.updated` / `section.moved` / `section.deleted` | 1 | |
| `project.created` / `project.updated` / `project.archived` / `project.unarchived` / `project.deleted` / `project.restored` | 1 | `changes`, `version` (updated); channels `project:<id>` + `team:<id>` |
| `project.member_added` / `project.member_updated` / `project.member_removed` | 1 | user_id, role (channels also `user:<id>`) |
| `comment.created` / `comment.edited` / `comment.deleted` / `comment.restored` | 1 | `task_id`, `mentioned_user_ids` (newly mentioned people also get `user:<id>`) |
| `reaction.added` / `reaction.removed` | 1 | `task_id`, `emoji` |
| `task.follower_added` / `task.follower_removed` | 1 | `user_id` |
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

## 3. WebSocket protocol (`/ws`) — implemented (S2.1.1), see `momentum/realtime/router.py`

The Phase-0 sketch of this section (batched `subscribe`/`channels`, a separate `replay`
message, client-initiated pings) was simplified once it came time to actually build and
test it; what shipped:

- Auth: the same session cookie/header as the REST API — `AuthProvider.authenticate()`
  only reads cookies/headers, which a `WebSocket` carries the same as a `Request`.
  Unauthenticated connections are closed with code 4401; realtime disabled
  (`MOMENTUM_REALTIME_ENABLED=false`) closes with 4503.
- Client → server, one channel per message (simpler than batching; the client just calls
  it once per channel it wants):
  - `{"op":"subscribe","channel":"project:<id>","since":<id>|omitted}`. The server checks
    the same visibility rules as the REST API (`momentum.domain.access`) before
    subscribing. Denied: `{"type":"denied","channel":"…","reason":"<error code>"}`.
    `since=0` means "everything you have" (first-ever subscribe on this device);
    omitting `since` means "just start live" (no backlog).
  - `{"op":"unsubscribe","channel":"…"}`
  - `{"op":"pong"}` — replies to the server's ping (see below).
- Server → client:
  - `{"type":"hello","connection_id":"…"}` right after accept.
  - `{"type":"subscribed","channel":"…"}` once a subscribe (and any backlog) is done.
  - `{"type":"event","id":…,"event":"task.updated","entity_type":…,"entity_id":…,"data":…,"actor":…,"request_id":…}`
    — the outbox envelope, flattened; sent both for backlog and for live events.
  - `{"type":"resync","channel":"…"}` when a requested backlog is over 500 events (the
    client should refetch that channel's data instead of trusting a giant replay).
  - `{"type":"ping"}` every 25s from the **server**, expecting `{"op":"pong"}` within
    45s more or the server closes the connection — server-initiated because it's the
    server that needs to reclaim resources for a browser tab that silently vanished
    (backgrounded/suspended tabs can stop running client timers but leave the socket
    looking open).
- Backlog channels: each `subscribe` with a `since` replays that one channel's history
  above it (`events_outbox` filtered by `workspace_id`, `id > since`, and a Postgres JSONB
  `?` containment check on `payload->'channels'`), oldest first, capped at 500 rows.
- Reconnect: left to the frontend client (S2.1.2, not yet built) — exponential backoff,
  re-subscribe every channel it cares about with `since` set to the last id it saw (its
  own remembered id takes priority over the durable `consumer_offsets` row, which is only
  a fallback for "this device forgot its own cursor").
- Multi-instance: every instance runs its own listener + Hub and dispatches independently
  to its own local connections (see §1) — no sticky sessions needed.

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
