# Testing Strategy

## 1. Pyramid

| Layer | Tool | Scope | Runs in |
|---|---|---|---|
| Unit (backend) | pytest | Pure functions: ordering, NL date helpers, permission matrix, claim parsing, rule condition evaluation, cost calc | `make check` |
| Service integration | pytest + **testcontainers Postgres (pgvector image)** | Services with a real DB: activity, outbox, undo, permissions in SQL, cycles, multi-homing | `make check` |
| API | pytest + httpx `AsyncClient` | Routing, schemas, auth modes, problem+json, CSRF, pagination | `make check` |
| Realtime | pytest | WS subscribe/permission deny/replay using the ASGI test client | `make check` |
| Jobs | pytest | Job functions invoked directly + Procrastinate in-memory connector for scheduling | `make check` |
| AI (deterministic) | pytest with `LLM_MODE=mock` | Tool registry schemas, dry-run previews, action lifecycle, context builders (golden snapshots), policy matrix | `make check` |
| AI evals | `momentum.ai.evals` runner | Quality of prompts/agents against fixtures (mock or live) | `make evals` (live nightly/manual) |
| Frontend unit/component | Vitest + Testing Library + MSW | Components, hooks, reducers, keyboard behavior | `make check` |
| E2E | Playwright (Chromium) against `make dev` stack with seed data | Critical user journeys | `make e2e` (before phase exit) |
| Portability | pytest + Vitest | Mounting under base path, non-default schema | `make check` |
| Accessibility | Playwright + axe | Key pages have no serious violations | Phase 8 |

## 2. Fixtures and factories

- `tests/factories.py`: factory-boy style async factories: `make_workspace`, `make_user(role=…)`, `make_team`, `make_project(privacy=…)`, `make_task(**)`, `make_comment`.
- `ctx_for(user)` helper builds a `Ctx`.
- Each test runs in a transaction rolled back at the end (`db_session` fixture with nested SAVEPOINT). One container per test session.
- `assert_max_queries(n)` fixture counts SQL statements.
- `frozen_time` fixture (time-machine) for due-date logic.
- Seed data (`momentum seed`) is **synthetic**: workspace "Acme Demo", 12 users (incl. 1 admin), 3 teams, 8 projects, ~400 tasks with realistic distributions (overdue, completed, subtasks, comments).

## 3. What every slice must test (Definition of Done)

| Slice adds… | Required tests |
|---|---|
| A service function | Happy path; permission denied (each role that should fail); validation; activity row + outbox row written; undo restores state (if undoable) |
| An endpoint | 200/201 path; 401 unauthenticated; 403/404 permission; 422 validation; response schema matches |
| A list/query | Filters, ordering, pagination, visibility (private project excluded), `assert_max_queries` |
| An event type | Emitted with the correct channels; WS delivers only to permitted subscribers |
| A job | Idempotent on double execution; retries on transient errors |
| A UI component | Renders loading/empty/error; main interaction via user-event; keyboard path; a11y role/name |
| An optimistic mutation | Optimistic update applied; rollback on error; toast with Undo |
| An AI tool | JSON schema snapshot; dry-run preview diff; apply + undo; permission enforced even if the model requests it |
| A prompt/agent | Mock fixtures + eval cases with thresholds |
| A setting | Default + override test; documented |

## 4. Critical E2E journeys (grow per phase)

| # | Journey | Phase |
|---|---|---|
| J1 | Dev login → create team → create project → add 3 tasks → assign → set due → complete one → undo | 1 |
| J2 | Open task pane → edit description → add subtask → comment with @mention → mention appears in the other user's inbox | 1–2 |
| J3 | Reorder tasks by drag within and across sections; persists after reload | 1 |
| J4 | Board: drag card between columns; calendar: drag to reschedule | 2 |
| J5 | Two browsers: edit in one, see update live in the other | 2 |
| J6 | Asana import (against a recorded fixture API) → projects visible with correct counts | 2 |
| J7 | ⌘K "assign all overdue tasks in Website Revamp to Ana" → preview → apply → undo | 3 |
| J8 | Ask Mo "what's blocking launch?" → answer with citations (mock LLM) | 3 |
| J9 | Rule: "when moved to Done, notify owner" fires | 4 |
| J10 | Assign task to Teammate agent → result comment → review | 5 |

## 5. Frontend testing conventions

- MSW handlers in `src/momentum/mocks/handlers/*` are generated from the same OpenAPI types (typed responses).
- Test by role/label, not class names.
- Keyboard: every list/pane test includes at least one keyboard-only path.
- Visual regression is not in v1 (maybe Phase 8 with Playwright screenshots for key screens).

## 6. AI evals

**Structure:**
```
momentum/ai/evals/
├── cases/<feature>/*.yaml        # input context (synthetic workspace snapshot refs), user input, expectations
├── fixtures/workspaces/*.json    # small synthetic workspaces for evals
├── fixtures/mock_responses/…     # recorded/handwritten model outputs for mock mode
└── runner.py                     # runs cases, scores, prints table, writes reports/evals/<date>.json
```

**Case example (`cases/command/assign_overdue.yaml`)**
```yaml
feature: command
workspace: small_team_v1
user: ravi
input: "assign all overdue design tasks in Website Revamp to Ana"
expect:
  tools_called_include: [search_tasks]
  proposed_operations:
    all_of: { tool: update_task, patch: { assignee: ana } }
    target_keys_equal: [T-12, T-15, T-19]
  no_writes_applied: true
```

**Scorers:** exact/structural match (tools, targets, fields), citation validity (every `[T-n]` exists and is visible to the user), groundedness (claims map to context. LLM-as-judge with the `smart` alias is allowed only in live mode, with a rubric), JSON-schema validity, latency and cost.

**Thresholds (initial):** command target accuracy ≥ 90%; status report citation validity 100% and judge score ≥ 4/5; triage field accuracy ≥ 80%; meeting action-item recall ≥ 85%. A prompt/model change that drops a score by > 5 points fails the eval gate.

**Modes:** `make evals` uses mock responses (checks plumbing and scorers). `EVALS_LIVE=1 make evals` hits the configured LiteLLM (run before merging prompt changes and weekly).

## 7. Performance checks (Phase 8)

- API: `locust` scenario for 15 concurrent users. p95 < 150 ms for list/patch endpoints on a 20k-task workspace.
- Frontend: list with 2,000 tasks, scripted scroll + edits, no long tasks > 100 ms (Playwright trace).
