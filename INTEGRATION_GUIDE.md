# Momentum Integration Guide: Lifting Momentum into Another Project

**Audience:** a developer, or an AI coding agent working inside a *host* codebase, who needs to bring Momentum into that project.
**Status:** living document. Updated at every phase exit (CLAUDE.md §5). Reflects the code as of the latest STATUS.md entry.

---

## 0. Instructions for an AI agent reading this inside a host repo

1. Read this whole file, then `CLAUDE.md` and `docs/architecture/embedding-and-portability.md` in the Momentum source.
2. Inspect the host: backend framework, auth mechanism, database, frontend framework/router/styling, deployment. Fill in the **host profile** in §2.
3. Choose an integration mode from §3 using the decision table. Prefer the least invasive mode that meets the goal.
4. Follow that mode's checklist in §4 step by step. Don't modify Momentum internals unless §6 says an adapter is the intended extension point.
5. Run the verification suite in §7. Report which checks pass, and any adaptation you made, in a short "Integration report".
6. Never copy real data between environments without the owner's approval. Move data only with `momentum export/import` or `pg_dump -n <schema>` (§5).

---

## 1. What Momentum is (in one screen)

| Part | Technology | Location |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Procrastinate (Postgres job queue) | `apps/api/momentum` (installable package `momentum`) |
| Database | PostgreSQL 16 + `pgvector`, `pg_trgm`, `citext`; **everything in one schema** (`MOMENTUM_DB_SCHEMA`, default `momentum`) | Migrations in `apps/api/momentum/migrations` |
| Frontend | React 19, TypeScript, Vite, React Router 7, TanStack Query, Tailwind v4 (scoped), Radix | `apps/web/src/momentum` (embeddable module) |
| Auth | Pluggable `AuthProvider`: `dev`, `easyauth-sim`, `easyauth` (Azure App Service), `oidc` (planned), **`host`** (your app authenticates) | `apps/api/momentum/auth` |
| AI | OpenAI-compatible gateway (LiteLLM, Portkey, …) with model aliases | `apps/api/momentum/ai` (Phase 3+) |
| Config | Environment variables with prefix `MOMENTUM_` (backend), runtime config endpoint for the SPA | `docs/architecture/configuration.md` |

**Portability guarantees (enforced by tests in `make check`):**
- Importing `momentum` has no side effects (no DB connection, no globals).
- The backend can be mounted under a base path inside a host FastAPI app and can use the host's authentication (`tests/test_portability.py`).
- Migrations create objects **only** in the configured schema; `public` is untouched apart from `CREATE EXTENSION IF NOT EXISTS`.
- Job-queue tables live in the Momentum schema; queue names are prefixed `momentum_`; the NOTIFY channel is `<schema>_events`.
- The frontend runs under any base path; API calls and links are prefixed (`apps/web/src/momentum/app.test.tsx`).
- Styles are scoped to `.momentum-root`; Tailwind's global preflight is not used; fonts are self-hosted.

---

## 2. Host profile (fill this in first)

| Question | Host answer |
|---|---|
| Backend language/framework | e.g., FastAPI / Django / Node / .NET / Java |
| How users authenticate (session cookie, JWT, Easy Auth, OIDC, API gateway) | |
| Where the user's identity is available in a request (header, `request.state.user`, token claims) | |
| Database engine and version; can we add a schema + extensions? | |
| Frontend framework, router, styling system | |
| Deployment target (App Service, Kubernetes, VM) and whether one or two processes are allowed | |
| Multi-tenant? (tenant ↔ Momentum `workspace_id` mapping) | |
| Required URL prefix for Momentum (e.g., `/work`) | |

---

## 3. Choose an integration mode

| Mode | What it means | Use when | Effort |
|---|---|---|---|
| **A. Side-by-side app** | Deploy Momentum as its own app (own container) on a sub-domain or path behind the same login (e.g., the same Easy Auth / Entra app or a shared gateway) | The host is not Python, or you want zero coupling | Lowest |
| **B. Mounted backend + embedded UI** | Install the `momentum` package in the host's Python backend and `mount_momentum()` under a prefix; render `<MomentumApp basePath>` inside the host's React app | The host backend is FastAPI/Starlette and the frontend is React | Medium |
| **C. Source transplant** | Copy `apps/api/momentum` and `apps/web/src/momentum` into the host monorepo as modules and adapt them | You need deep customization or a single codebase | Highest (you own the fork) |

**Decision rule:** host backend not FastAPI/Starlette → **A**. FastAPI + React → **B**. Only choose **C** if A/B can't meet a hard requirement; record why.

---

## 4. Step-by-step checklists

### Mode A: Side-by-side app

1. Build the image: `docker build -f infra/docker/Dockerfile -t momentum:<sha> .`
2. Provision Postgres 16 with `vector`, `pg_trgm`, `citext` allowed (Azure: add them to `azure.extensions`).
3. Configure auth:
   - Same Azure App Service auth → `MOMENTUM_AUTH_MODE=easyauth`, same Entra tenant; set `MOMENTUM_ALLOWED_TENANT_IDS`, `MOMENTUM_ADMIN_ROLE`.
   - Behind a gateway that injects identity headers → implement a small provider (§6.1) or use `host` mode through a thin ASGI wrapper.
4. Set `MOMENTUM_PUBLIC_BASE_URL` and, if served under a path by a reverse proxy, `MOMENTUM_BASE_PATH=/work` and build the SPA with `VITE_MOMENTUM_BASE_PATH=/work`.
5. Run `momentum migrate`, then start the container (`momentum serve`). Health check: `GET /healthz`.
6. Link from the host UI to Momentum (menu item, deep links such as `/work/task/<id>`).

### Mode B: Mounted backend + embedded UI

**Backend (host FastAPI):**
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from momentum import Settings, mount_momentum
from momentum.app import momentum_lifespan
from momentum.auth import Principal

async def resolve_principal(request: Request) -> Principal | None:
    user = getattr(request.state, "user", None)          # ← adapt to the host's auth
    if not user:
        return None
    return Principal(provider="host", subject=str(user.id), email=user.email,
                     name=user.display_name, roles=tuple(user.roles))

momentum_settings = Settings(base_path="/work", auth_mode="host", serve_spa=False,
                             worker_mode="embedded")   # or "separate" + run `momentum worker`

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with momentum_lifespan(app.state.momentum_subapp):
        yield

app = FastAPI(lifespan=lifespan)
mount_momentum(app, settings=momentum_settings, resolve_principal=resolve_principal)
```
- Add `momentum` as a dependency (path or git dependency on `apps/api`).
- Run migrations in the host's deploy step: `MOMENTUM_DATABASE_URL=… MOMENTUM_DB_SCHEMA=momentum momentum migrate`.
- The host's auth middleware must run **before** the mount so `request.state.user` is set, or resolve the user inside `resolve_principal` from the host's session/token directly.
- CSRF: Momentum requires `X-Requested-With: momentum` on cookie-authenticated mutations. The Momentum UI sends it; host code calling Momentum's API must send it too, or use a bearer API token.

**Frontend (host React app):**
```tsx
import { MomentumApp } from '@momentum/web';     // workspace package from apps/web (src/momentum/index.ts)

// In the host router, give Momentum its own subtree:
<Route path="/work/*" element={<MomentumApp basePath="/work" />} />
```
- Momentum creates its own router (with `basename`), QueryClient, stores, and toaster inside `.momentum-root`. It does not use the host's providers.
- If the host also uses Tailwind and there's a class conflict, enable the prefixed build variant (ADR-0006); if there's a font or reset conflict, the scoped reset in `styles/base.css` is the only place to adjust.
- Deep integration (sharing the host's router instead of a nested one) is possible with `momentumRoutes(config)` plus `MomentumProvider`; prefer the nested app until there's a need.

### Mode C: Source transplant

1. Copy `apps/api/momentum` → `<host>/backend/momentum` and `apps/web/src/momentum` → `<host>/frontend/src/momentum`. Keep the folder names so imports and docs still match.
2. Copy `docs/`, `CLAUDE.md`, and this file into `<host>/docs/momentum/`, so future AI sessions keep the rules.
3. Merge dependencies (`pyproject.toml`, `package.json`); keep Momentum's minimum versions.
4. Replace the auth provider with a host adapter (§6.1), and keep `Principal` → `resolve_user` intact.
5. Keep the dedicated DB schema, even inside the host database.
6. Keep `make check` equivalents: Momentum's tests must run in the host CI (point `MOMENTUM_TEST_DATABASE_URL` at a test DB).
7. Record every deviation in `docs/momentum/ADAPTATIONS.md` (what changed, why, and how to re-apply on upstream updates).

---

## 5. Data: moving Momentum data between environments

| Need | Command |
|---|---|
| Same Postgres major version | `pg_dump -n momentum -Fc > momentum.dump` → `pg_restore -d <target> momentum.dump` |
| Different infra / partial | `momentum export --out bundle.zip [--with-files]` → `momentum import bundle.zip` (Phase 8) |
| New identity provider or tenant | Keep `MOMENTUM_IDENTITY_LINK_BY_EMAIL=true`; users re-link by email on first login |
| Different embedding model | `momentum reindex` (Phase 3+) |
| Attachments | Copy the storage container (AzCopy / `aws s3 sync`), or use the bundle with `--with-files` |
| From Asana | Use the importer (Phase 2, `docs/integrations/asana-import.md`) |

---

## 6. Extension points (adapt here, not elsewhere)

### 6.1 Auth adapter
Implement the `AuthProvider` protocol (`momentum/auth/base.py`): `authenticate(request) -> Principal | None`, `login_url()`, `logout_url()`. Register it in `momentum/auth/factory.py` (Mode C) or pass `resolve_principal` (Mode B). Everything downstream (user provisioning, identity linking, roles, permissions) stays unchanged.

### 6.2 Tenancy
Momentum runs in single-workspace mode (`MOMENTUM_DEFAULT_WORKSPACE_SLUG`). For a multi-tenant host, map tenant → workspace in `momentum/auth/identity.py::resolve_user` (the only place that picks a workspace). Every table already carries `workspace_id`.

### 6.3 Storage (Phase 2+)
`StorageBackend` (`momentum/storage/`) with `local` and `azure_blob`. Add a new backend for S3/GCS without touching features.

### 6.4 AI gateway (Phase 3+)
Any OpenAI-compatible endpoint: set `MOMENTUM_LLM_BASE_URL`, `MOMENTUM_LLM_API_KEY`, and map the aliases (`fast`, `default`, `smart`, `embed`). If the gateway wants its key in its own header (Portkey: `x-portkey-api-key`), set `MOMENTUM_LLM_API_KEY_HEADER`; put non-secret routing headers in `MOMENTUM_LLM_EXTRA_HEADERS`. Run `momentum llm-check` (prints a pass/fail table; exit code 1 on any failure). The gateway is built per app in the lifespan (`app.state.momentum.llm`), so a host running several Momentum sub-apps gets one gateway each. Every call writes an `llm_calls` row in Momentum's schema.

### 6.5 Look and feel
Design tokens in `apps/web/src/momentum/styles/tokens.css` (scoped). To match a host brand, override the token values; component code never contains raw colors.

### 6.6 Realtime (Phase 2+)
`GET /ws` (docs/architecture/realtime-jobs-events.md §3) is a plain FastAPI websocket route, mounted at the app root alongside the API and SPA — under `settings.base_path` the same way they are, no separate config. Any reverse proxy or gateway in front of Momentum (Mode A/B) must forward websocket upgrades (`Connection: Upgrade`) for that path, not just HTTP; Azure App Service and most modern proxies do this by default, but confirm with the host's ops docs. Set `MOMENTUM_REALTIME_ENABLED=false` to turn the whole feature off (the route then closes every connection with code 4503) if the host can't proxy websockets yet — the UI falls back to its Phase 1 behavior (refetch on window focus).


### 6.7 Agents (Phase 5+): extending them from the host (ADR-0009)
Every agent acts as its own user account (`<key>@agents.momentum.invalid`, never signs in) and works only in projects it was explicitly added to. When a person asks it for something, it sees only what both can see. A host adds its own agents without forking Momentum, through one `Extensions` object (`momentum.agents.extensions`):

```python
# acme/momentum_ext.py
from momentum.agents.extensions import Extensions, HandlerResult, HandlerRun
from momentum.ai.tools.base import ToolContext, ToolResult, tool

@tool(name="lookup_customer", description="Look up a customer in our CRM.", risk="read", scopes=("tasks:read",))
async def lookup_customer(tc: ToolContext, args: LookupArgs) -> ToolResult: ...

async def upload_to_erp(run: HandlerRun) -> HandlerResult:
    task = await run.task()                      # what it was assigned (visible to it)
    text = await run.read("get_attachment_text", {"task": str(task.id)})
    run.step("Pushed 42 rows")                  # a line on the run's timeline
    await run.attach("report.txt", b"...", "text/plain")
    run.propose("update_task", {"task": str(task.id), "priority": "low"})  # for the requester to apply
    return HandlerResult(text="Uploaded 42 rows.")  # answered in the task's thread

extensions = Extensions(
    tools=[lookup_customer],
    handlers={"acme.erp:upload": upload_to_erp},
    definition_dirs=["acme/agents"],             # acme/agents/erp_uploader.yaml: kind: handler, handler: acme.erp:upload
)
```

- **Wire it in** with `MOMENTUM_AGENT_EXTENSIONS=acme.momentum_ext:extensions`. The web app **and every worker** load it, so set it wherever agents run. `create_app(extensions=…)` / `mount_momentum(extensions=…)` also work in-process. `momentum agents install` then installs the host's definitions (disabled, `source: host`) next to the starters. Keys must not collide.
- **Host tools** follow the built-in rules: a `risk`, arguments as a Pydantic model, writes only through Momentum's services (so they're previewable and undoable). A definition's `tools` may name them.
- **Handler agents** (`kind: handler`) run your function with the same triggers, access, scope, timeout, kill switches, runs page and trace as a model-driven agent. `HandlerRun` gives:
  - `ctx` (for calling services), `task()`, `input`, `trigger`;
  - `read(tool, args)`;
  - `complete(messages)` (billed to the agent's budget);
  - `step()`, `comment()`, `attach()`;
  - `propose()`: sent to the person the run is for.

  Autonomy doesn't apply to your code, but the service guards do: no deletes, no completing others' tasks, no approval decisions. An exception fails the run with its message (on the runs page, for admins and the requester).
- **Outside the process:** see §6.8.

### 6.8 Calling Momentum from a script (API tokens, S5.1.6)
Create a token under **Account menu → API tokens** (`/settings/tokens`), pick its scopes (`read`, `tasks:write`, `attachments:write`, `ai`) and an expiry (≤ 1 year). Copy the secret: it's shown once. For a script that should show up **as an agent**, an admin issues the token on that agent (`POST /api/v1/agents/{id}/tokens`), and the agent must have been given the projects it works in.

```bash
curl -H "Authorization: Bearer $MOMENTUM_TOKEN" https://momentum.example/api/v1/projects
curl -X POST -H "Authorization: Bearer $MOMENTUM_TOKEN" -H "Content-Type: application/json" \
     -d '{"title": "Customer 42: upload complete"}' https://momentum.example/api/v1/projects/$PROJECT/tasks
```

A token acts as its owner, only within its scopes (403 `token_scope` otherwise). Changes are recorded with `created_via="api"` and are undoable in the app. Revoke it on the same page (agent tokens: `DELETE /api/v1/me/tokens/{id}` as an admin). `MOMENTUM_API_TOKENS_ENABLED=false` turns tokens off entirely. The OpenAPI schema at `/api/v1/docs` lists every endpoint.
---

## 7. Verification suite (run after integrating)

| # | Check | How |
|---|---|---|
| V1 | Health | `GET <base>/healthz` → `{"status":"ok"}` |
| V2 | Runtime config | `GET <base>/api/v1/config` → `api_base` includes the prefix |
| V3 | Auth | Logged-in host user → `GET <base>/api/v1/me` returns that user; anonymous → 401 with `login_url` |
| V4 | Schema isolation | `select count(*) from pg_tables where schemaname='public'` unchanged after `momentum migrate` |
| V5 | UI under prefix | Open `<base>/`: shell renders, links start with `<base>/`, no console errors |
| V6 | Styles isolated | Host pages look identical with and without Momentum mounted |
| V7 | Background jobs | Worker logs `worker_heartbeat` within 5 minutes |
| V8 | Momentum test suite | `make check` (or the host CI equivalent) is green |
| V9 | User journeys | `make e2e` (Playwright; needs Postgres and a database name ending in `_e2e`, see `tools/e2e/serve.sh`) |
| V10 | Realtime | Open two browser tabs logged in as different users on the same project; edit a task in one, see it update in the other within ~1s. If it doesn't and the browser console shows repeated WS connection failures, the host's proxy is likely not forwarding websocket upgrades (see §6.6) |

---

## 8. Change log

| Date | Phase | Integration-relevant change |
|---|---|---|
| 2026-09-23 | 0 | Initial: `create_app`, `mount_momentum` + `momentum_lifespan`, `host` auth mode, schema-scoped migrations and job queue, embeddable `MomentumApp` with `basePath`, scoped styles |
| 2026-09-23 | 1 | Migrations 0002-0006 in the `momentum` schema (teams, projects, sections, tasks, followers, comments, mentions, reactions, per-user My Tasks placements); all new API under `/api/v1` (`/home`, `/me/tasks`, `/me/prefs/views/*`, `/tasks/*`, `/comments/*`, `/mentions/search`, `/undo`). UI stores only per-device conveniences in `localStorage` under the `momentum.` prefix (drafts, collapsed sections, last quick-add project). Responsive shell: below 900px the sidebar is a drawer and panes go full-screen, so a host page embedding the UI should give it the full viewport width. E2E journeys runnable in the host via `make e2e` (V9). |
| 2026-09-24 | 2 | S2.1.1 realtime: `GET /ws` (websocket), migration 0007 (`consumer_offsets`, an index on `events_outbox`); `MOMENTUM_REALTIME_ENABLED` (default true) controls it. See §6.6 and V10. |
| 2026-09-24 | 2 | S2.1.2 realtime frontend client (`apps/web/src/momentum/lib/realtime/`). No new host-facing surface: it just talks to the `/ws` route from S2.1.1. A host embedding the UI only needs to keep forwarding websocket upgrades for that path (§6.6, V10) — nothing else changes. |
| 2026-09-26 | 3 | S3.1.1 LLM gateway: migration 0015 (`llm_calls`, usage only, no prompt bodies); `momentum llm-check`; new settings `MOMENTUM_LLM_API_KEY_HEADER`, `MOMENTUM_LLM_EXTRA_HEADERS`, `MOMENTUM_LLM_FIXTURES_DIR` (plus the already-documented `LLM_EMBED_BATCH`/`TIMEOUT_S`/`MAX_RETRIES`/`SUPPORTS_STREAMING_TOOLS`/`PRICE_TABLE`, `AI_MONTHLY_BUDGET_USD`, now read). **Startup now fails in `MOMENTUM_ENV=production` unless `MOMENTUM_LLM_MODE=gateway` or `MOMENTUM_AI_ENABLED=false`.** New runtime dependencies: `openai` (ADR-0004; brings `httpx2`), `pyyaml` (was already transitive). See §6 (LLM gateway). |
| 2026-09-26 | 3 | S3.1.2–S3.1.4: migrations 0016 (`ai_actions`) and 0017 (`embeddings` vector(1024) + HNSW, `ai_summaries`): the `vector` extension (installed by 0001) is now actually used. New API `/api/v1/ai/actions/*`; new periodic jobs `expire_ai_actions` and `index_embeddings` (queue `momentum_ai`, needs a worker); CLI `momentum reindex`; settings `MOMENTUM_LLM_RERANK_MODEL`, `MOMENTUM_AI_RERANK` (off). A host moving data in or out can drop and rebuild `embeddings` with `momentum reindex` (derived data). |
| 2026-09-26 | 3 | **Phase 3 exit** (no migration, endpoint or new setting). Host-relevant: (1) `MOMENTUM_AI_MONTHLY_BUDGET_USD` is dollars, so it only enforces if `MOMENTUM_LLM_PRICE_TABLE` prices the resolved model ids; with no price table spend counts as $0 and the budget never trips (tokens are always recorded). (2) `momentum evals` (`EVALS_LIVE=1` for the real gateway) needs a Postgres role that may create/drop its own `*_evals` database (`MOMENTUM_EVALS_DATABASE_URL`); it never touches the app database. (3) AI read-tool output gained `blocked_by` on task briefs (a blocker the reader cannot see is counted, never named; `get_task` now follows the same rule), `search_tasks.blocked`, and `from`/`to` on moved dates; hosts that register extra tools or replay tool fixtures should expect these keys. (4) `GET /ai/admin/usage` gained `unpriced_models`; `llm-check` gained a `pricing` row. (5) The e2e server (`tools/e2e/serve.sh`) now pins `MOMENTUM_LLM_MODE=mock` and Playwright starts it via `bash`, so it also runs on Windows. |
| 2026-09-29 | 5 | S5.1.6: API tokens (`Authorization: Bearer mtm_…`) accepted in every auth mode via `ApiTokenProvider` wrapping the configured provider; `/me/tokens`, `/agents/{id}/tokens`; `/settings/tokens`. No migration (`api_tokens` existed). A host proxy must pass the `Authorization` header through to Momentum. See §6.8. |
| 2026-09-29 | 5 | S5.0.2 public forms security review: new setting `MOMENTUM_TRUSTED_PROXY_HOPS` (default 0). **Set it to the number of proxies in front of Momentum** (Azure App Service: 1) so the public-form rate limit sees real visitor addresses; `momentum serve` no longer trusts `X-Forwarded-*` from anyone unless it is above 0. A host that mounts Momentum under its own server: forward `X-Forwarded-For` and set the hop count to match. Public (anonymous) forms no longer show or accept assignee questions; signed-in submissions may only assign the project's people. No migration. |
| 2026-09-29 | 5 | S5.3.1 Pulse: Momentum now ships a built-in handler, `momentum.daily_digest`; built-in handler names win over a host's, so don't register handlers under `momentum.*`. Schedule triggers gained optional `at: digest_time` (with `timezone: user`). Re-run `momentum agents install --only daily_digest` (the definition changed from a model agent to the built-in handler). No migration or setting. |
| 2026-09-29 | 5 | S5.3.2 Sorter: new AI tool `set_field_value`; `get_task` results gain `custom_fields` (hosts replaying tool fixtures should expect it). Custom-field changes now record a `task.field_set` activity with an undo (they had none), so they appear in activity exports. Event triggers gained an optional `filter.top_level`. Re-run `momentum agents install --only triage`. No migration or setting. |
| 2026-09-29 | 5 | S5.3.3 Herald: second built-in handler `momentum.status_reporter`; schedule triggers gained optional `per: project`. For handler authors: `HandlerRun.llm` is a model handle billed to the run, for calling Momentum's AI features (e.g. `draft_status`) from a handler. Re-run `momentum agents install --only status_reporter`. No migration or setting. |
| 2026-09-29 | 5 | S5.3.4 Nudge: **migration 0030** (`my_task_placements.nudge_snoozed_until`, nullable); `PUT /api/v1/me/tasks/{id}/nudge-snooze`; `TaskDetailOut.my_nudge_snoozed_until`; notification prefs gain `nudge_me`; third built-in handler `momentum.nudger`. Re-run `momentum agents install --only nudger`. No new setting. |
| 2026-09-29 | 5 | S5.1.5 (ADR-0009): `Extensions` (host tools, handler agents, definition dirs) via `MOMENTUM_AGENT_EXTENSIONS` or `create_app`/`mount_momentum(extensions=…)`; new read tool `get_attachment_text`; `get_task` lists attachment names. See §6.7. |
| 2026-09-29 | 5 | S5.1.4: new daily job `demote_agents` (maintenance queue); `GET /agents/{id}/stats`; workspace AI setting `allow_medium_auto` (in `workspaces.settings['ai']`, off unless set). No migration. |
| 2026-09-29 | 5 | S5.0.1 + S5.1.3: the app shell always subscribes to `user:<me>` (inbox and bell live). New endpoints `GET /agents/{id}/runs`, `GET /agents/runs/{run_id}`; new routes `/agents/:agentId`, `/agents/runs/:runId`. **Permission semantics:** `Ctx.acting_for` is now honoured by `domain/access.py` (intersection of both actors, lower role), used for runs a person asked an agent to do. A host setting `acting_for` gets the same behaviour. |
| 2026-09-28 | 5 | S5.1.2 agent runtime: migration 0029 (`agents.enabled_at`); jobs `agent_triggers` (default queue) and `run_agent_runs` (`momentum_ai` queue), both every minute, **so agents need the worker**; setting `MOMENTUM_AGENTS_ENABLED`; endpoints `POST /agents/{id}/run`, `GET/PUT /workspace/settings` (timezone for agent schedules, stored in `workspaces.settings`). **Every outbox event payload gains `via`** (a host consuming events sees one more key). New consumer cursor `agents` in `consumer_offsets`. |
| 2026-09-28 | 5 | S5.1.1 agents: migration 0028 (`agents`, `agent_runs`; FKs `users.agent_id → agents`, `llm_calls.agent_run_id → agent_runs`; notification kind `agent_alert`). API under `/api/v1/agents` (+ `POST /agents/install`). New `create_app`/`mount_momentum` argument `agent_definition_dirs` (§6.7), CLI `momentum agents install|list`, settings `MOMENTUM_AGENT_MAX_STEPS`, `MOMENTUM_AGENT_TIMEOUT_S`. `croniter` becomes an explicit runtime dependency (it was already installed through Procrastinate). Agent accounts are rows in `users` with `is_agent=true`: an identity provider can never sign in as one, and a host copying users between environments should copy `agents` with them. |
| 2026-09-27 | 4 | S4.1.1 rules engine: migration 0021 (`rules`, `rule_runs`), API under `/api/v1/rules`, a `run_rules` job (default queue, every minute; needs the worker), new setting `MOMENTUM_RULES_ENABLED` (default true). Outbox events now carry `depth` in their payload. |
| 2026-09-27 | 4 | S4.2.1 form builder + public forms: migration 0024 (`forms`, `form_submissions`); API under `/api/v1/forms` (authenticated CRUD + internal submit) and, new for this repo, `/api/v1/public/forms/*` — the first **unauthenticated** write path, mounted under `/api/v1/public/` (already exempt from `CsrfMiddleware`, see `CSRF_EXEMPT` in `momentum/app.py`) and never using `CtxDep`. A host reverse-proxying or embedding Momentum must let that prefix through without requiring a session. New settings `MOMENTUM_FORMS_IP_HASH_SALT` (must be set, not the dev default, in production — same rule as `MOMENTUM_SECRET_KEY`), `MOMENTUM_FORMS_RATE_LIMIT_PER_IP`/`PER_FORM`/`WINDOW_MINUTES`. Rules gained the `form.submitted` trigger (optionally scoped to one form); `nl_rule` prompt bumped to v3. |
| 2026-09-28 | 4 | S4.2.2 conversational intake: migration 0025 (`forms.conversational`); `POST /api/v1/forms/{id}/converse[/submit]` and the public `/api/v1/public/forms/{token}/converse[/submit]` (same unauthenticated-prefix rule as S4.2.1). No new setting or table — the conversation is stateless (client resends the transcript each turn), and submitting reuses S4.2.1's one write path. No new host-facing surface beyond the routes themselves. |
| 2026-09-28 | 4 | S4.3.1 project templates: migration 0026 (`templates`, shared with S4.3.2's task templates); API under `/api/v1/templates`. No new setting. A template's payload never stores a raw person id (assignees become roles, resolved back to people only at "new from template" time) or a raw section id in its captured rules (section index instead) — worth knowing if a host ever needs to inspect or migrate template data directly. |
| 2026-09-28 | 4 | S4.3.2 task templates: no new migration (reuses S4.3.1's `templates` table, `kind="task"`) or setting; `POST /api/v1/templates/from-task` and `.../{id}/new-task`. |
| 2026-09-28 | 4 | S4.3.3 template from description (AI): no new migration, table or setting; `POST /api/v1/ai/templates/from-brief` + `.../from-brief/save`, in their own `momentum/ai/templates_router.py` module (domain must not import AI). Saves through the same `service.save_template_payload()` write path and the same role-placeholder payload shape as S4.3.1, so a host that already handles S4.3.1's templates needs no extra work for AI-drafted ones. |
| 2026-09-28 | 4 | S4.4.1 approvals: no new migration — `tasks.type`/`tasks.approval_state` and the `approval_requested`/`approval_decided` notification kinds were already in the schema, unused until now. `POST /api/v1/tasks/{id}/convert` accepts `approval` as a third type; new `POST /api/v1/tasks/{id}/approval/decide`. A new rules trigger `approval.decided` (optional `decision` filter). No new setting; a host that already forwards `/api/v1/tasks/*` and `/api/v1/rules/*` needs no extra wiring. |
| 2026-09-28 | 4 | S4.4.2 recurring tasks: migration 0027 adds `tasks.recurrence_parent_id` (self-FK, nullable — a task auto-created as another's next occurrence). New job `scan_scheduled_recurrences` (`momentum_maintenance` queue, daily) — a host running the worker gets it automatically, same as every other periodic job; nothing new to configure. `TaskPatchIn` gained `recurrence` (previously write-only through create/quick-add). No new setting. |
| 2026-09-28 | 4 | **Phase 4 exit** (no migration, endpoint or new setting). Host-relevant finding, not yet fixed: the frontend's inbox page and topbar notification bell have no live realtime subscription of their own — `notification.created` (S2.5.1) only reaches a viewer already on Home or My Tasks (where `useChannel('user:<id>', …)` happens to be mounted). A host embedding the UI should expect the same gap until a follow-up slice live-subscribes those two surfaces. |
