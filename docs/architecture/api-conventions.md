# API Conventions

## 1. Basics

- Base path: `{MOMENTUM_BASE_PATH}/api/v1` (base path defaults to empty).
- JSON only, `snake_case` fields. Timestamps are ISO-8601 UTC (`2026-09-23T10:00:00Z`). Dates are `YYYY-MM-DD`.
- IDs are UUID strings. Tasks also expose `number` and `key` (`"T-123"`).
- The OpenAPI schema at `/api/v1/openapi.json` is the contract. The frontend types are generated from it (`make types`).
- Every router has tags matching its module. Every endpoint has `summary` and response models.

## 2. Resource shape

```
GET    /api/v1/projects/{id}
PATCH  /api/v1/projects/{id}
GET    /api/v1/projects/{id}/tasks?section_id=&completed=false&cursor=&limit=
POST   /api/v1/tasks
GET    /api/v1/tasks/{id}?include=subtasks,projects,fields,followers
PATCH  /api/v1/tasks/{id}
POST   /api/v1/tasks/{id}/complete        # verbs for state transitions
POST   /api/v1/tasks/{id}/move            # {project_id, section_id, before_id?, after_id?}
POST   /api/v1/tasks/bulk                 # {ids, patch} or {ids, op}
DELETE /api/v1/tasks/{id}                 # soft delete
POST   /api/v1/undo                       # {activity_id} or {batch_id}
POST   /api/v1/sections/{id}/move         # {after_id?, before_id?}: same neighbor contract for every ordered list
```

- `PATCH` bodies are partial. Only fields present are changed. Send `null` explicitly to clear a field.
- State transitions use explicit action endpoints (`/complete`, `/uncomplete`, `/approve`), not PATCH of internal flags.
- `include=` expands related data; the default responses stay small.

## 3. Mutation responses

Every mutation returns:

```json
{
  "data": { "...resource..." },
  "meta": { "activity_id": "…", "batch_id": null, "version": 7 }
}
```

The frontend shows **Undo** in the toast using `activity_id`/`batch_id`.

## 4. Lists and pagination

```json
{ "data": [ ... ], "meta": { "next_cursor": "opaque", "total": null } }
```

- Cursor pagination (opaque base64 of the sort key + id). `limit` defaults to 50, max 200.
- Project task lists return **all incomplete tasks** in one call up to 2,000 (the list view needs the full ordering). Completed tasks are paged separately.

## 5. Errors: RFC 9457 `application/problem+json`

```json
{
  "type": "https://momentum/errors/conflict",
  "title": "Version conflict",
  "status": 409,
  "code": "version_conflict",
  "detail": "Task was modified by someone else.",
  "errors": [{"field": "title", "message": "…"}],
  "request_id": "01J…"
}
```

| Domain error | HTTP | code |
|---|---|---|
| ValidationFailed | 422 | `validation_failed` (field errors) |
| NotFound | 404 | `not_found` (also used when the caller may not see the resource, to avoid leaking existence) |
| Forbidden | 403 | `forbidden` (visible but not allowed, e.g., a viewer trying to edit) |
| Conflict | 409 | `version_conflict`, `cycle_detected`, `duplicate` |
| Unauthenticated | 401 | `unauthenticated` (the SPA redirects to login) |
| RateLimited | 429 | `rate_limited` |
| AIUnavailable | 503 | `ai_unavailable` (the gateway is down; the UI degrades gracefully) |
| BudgetExceeded | 402 | `ai_budget_exceeded` |

## 6. Concurrency

- Resources with `version` accept an optional `If-Match: <version>` header (or a `version` body field). A mismatch → 409.
- The UI sends `If-Match` for description/brief edits (long text). For single-field inline edits it uses last-write-wins (Asana-like) to avoid friction, and realtime events keep clients fresh.

## 7. Idempotency

- `POST` endpoints that create resources accept an `Idempotency-Key` header (stored 24h in the `idempotency_keys` table: key, user_id, response hash). The importer, integrations, and AI apply always send it.

## 8. Streaming

- AI chat and long AI operations use **SSE** over `POST` (`text/event-stream`) through `fetch` streaming: events `token`, `tool_call`, `tool_result`, `citation`, `action_proposed`, `done`, `error`.
- Realtime entity updates use WebSocket (`/ws`), see `realtime-jobs-events.md`.

## 9. Auth on the wire

- Browser: a same-origin cookie (Easy Auth session in production; the `momentum_dev_session` cookie in dev). No bearer tokens in the SPA.
- Machines (MCP, scripts, webhooks): `Authorization: Bearer mtm_<token>` on excluded paths, or a provider signature (Slack).
- CSRF: cookie-authenticated mutating requests must carry the `X-Requested-With: momentum` header (set by the API client). The server rejects them otherwise. Cookies are `SameSite=Lax`.

## 10. Router checklist (per endpoint)

- [ ] Pydantic request/response models in `schemas.py` (no ORM objects leaked)
- [ ] `ctx: Ctx = Depends(get_ctx)`
- [ ] Calls exactly one service function (composition lives in services)
- [ ] Documented error codes in `responses=`
- [ ] API test for happy path + permission denial + validation error


## Undo (S1.4.3)

Every mutation returns `meta.activity_id` (or `meta.batch_id` for bulk actions); `POST /undo`
with either reverses it. Rules (enforced in `core/undo.py` and the handlers):

- only the person who made the change, or a workspace admin; within 24 hours; once;
- refused with `409 undo_conflict` if the thing changed again since (version, position or
  content checks in each handler), so an undo never overwrites someone's later work;
- the reversal's own activity is marked undone too, so feeds show neither;
- batches undo newest first as one unit.

Coverage is tested in `tests/test_undo_coverage.py`: a table of every Phase 1 mutation type
(teams, projects, members, sections, tasks, dates, descriptions, bulk actions, subtasks,
followers, comments) plus a static check that every recorded undo op has a handler. Add a row
there for every new mutation. In the UI, every mutation with an undo handle goes on the session
undo stack (`lib/undo.ts`); ⌘Z / Ctrl+Z outside text fields undoes the latest.
