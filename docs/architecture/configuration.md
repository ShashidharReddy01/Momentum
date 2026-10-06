# Configuration Reference

All settings are read by `momentum.core.settings.Settings` (pydantic-settings). **Env prefix: `MOMENTUM_`** (so Momentum never collides with a host project's variables). A `.env` file is read in local dev only.

Frontend build-time variables use the `VITE_MOMENTUM_` prefix, but the SPA prefers **runtime config** from `GET /api/v1/config` (so one built image works in every environment).

## Core

| Setting | Default | Description |
|---|---|---|
| `MOMENTUM_ENV` | `local` | `local` · `test` · `production` |
| `MOMENTUM_SECRET_KEY` | (required outside local) | Signing dev sessions, CSRF, tokens |
| `MOMENTUM_BASE_PATH` | `` | Mount prefix, e.g. `/momentum` when embedded |
| `MOMENTUM_PUBLIC_BASE_URL` | `http://localhost:5173` | Absolute links in Slack/email |
| `MOMENTUM_LOG_LEVEL` | `INFO` | |
| `MOMENTUM_LOG_FORMAT` | `console` (local) / `json` | |
| `MOMENTUM_DEFAULT_WORKSPACE_SLUG` | `default` | Single-workspace mode |
| `MOMENTUM_SERVE_SPA` | `true` | Serve built SPA from FastAPI (false when a host serves the UI) |
| `MOMENTUM_SPA_DIR` | (package `web/static`) | Directory with the built SPA (`index.html`), e.g. `apps/web/dist` locally |
| `MOMENTUM_DEFAULT_WORKSPACE_NAME` | `Momentum` | Name used when the default workspace is first created |

## Database

| Setting | Default | Description |
|---|---|---|
| `MOMENTUM_DATABASE_URL` | `postgresql+psycopg://momentum:momentum@localhost:5432/momentum` | Async SQLAlchemy URL |
| `MOMENTUM_DB_SCHEMA` | `momentum` | All tables + alembic version table live here |
| `MOMENTUM_DB_POOL_SIZE` / `_MAX_OVERFLOW` | `10` / `10` | Per web process. Budget: `MOMENTUM_WEB_WORKERS × (pool + overflow + 2)` must stay under Postgres `max_connections` (the app warns at startup above 80%). For ~150 people: 4 workers × (5 + 5 + 2) = 48 (Phase 7 load test) |
| `MOMENTUM_DB_AUTO_MIGRATE` | `false` (`true` local) | Run `alembic upgrade head` on startup under an advisory lock |

## Auth

| Setting | Default | Description |
|---|---|---|
| `MOMENTUM_AUTH_MODE` | `dev` | `dev` · `easyauth-sim` · `easyauth` · `oidc` · `host` |
| `MOMENTUM_ALLOWED_TENANT_IDS` | `` | Comma list; empty = any (dev only) |
| `MOMENTUM_ALLOWED_EMAIL_DOMAINS` | `` | Comma list |
| `MOMENTUM_BOOTSTRAP_ADMIN_EMAILS` | `` | First-login admins |
| `MOMENTUM_ADMIN_ROLE` | `Momentum.Admin` | IdP app role that grants admin |
| `MOMENTUM_SYNC_ADMIN_ROLE` | `true` | Keep admin in sync with the IdP role |
| `MOMENTUM_IDENTITY_LINK_BY_EMAIL` | `true` | Re-link identities by email (tenant moves) |
| `MOMENTUM_AUTO_PROVISION` | `true` | Create users on first login if allow-listed |
| `MOMENTUM_EASYAUTH_EMAIL_CLAIMS` | see auth doc | Claim precedence |
| `MOMENTUM_EASYAUTH_SIM_TENANT_ID` | fixed test GUID | Tenant id used by the local Easy Auth simulator |
| `MOMENTUM_EASYAUTH_TRUST_HEADERS` | `false` | Force-trust headers outside App Service (never in prod unless behind a trusted proxy) |
| `MOMENTUM_OIDC_ISSUER` / `_CLIENT_ID` / `_CLIENT_SECRET` | | oidc mode |
| `MOMENTUM_API_TOKENS_ENABLED` | `true` | Accept API tokens (`Authorization: Bearer mtm_…`) on `/api` (S5.1.6; MCP was dropped) |

## Worker and realtime

| Setting | Default | Description |
|---|---|---|
| `MOMENTUM_WORKER_MODE` | `embedded` | `embedded` · `separate` · `off` |
| `MOMENTUM_WEB_WORKERS` | `1` | Web server processes for `momentum serve` (1–32). One handles ~20 requests/s; ~150 active people need **4** (Phase 7 load test). Realtime fans out across processes via LISTEN/NOTIFY; the job queue de-duplicates scheduled jobs, so embedded workers in each process are safe |
| `MOMENTUM_WORKER_CONCURRENCY` | `4` | |
| `MOMENTUM_REALTIME_ENABLED` | `true` | |
| `MOMENTUM_RULES_ENABLED` | `true` | Kill switch for the rules executor (S4.1.1): rules stay editable but nothing fires |
| `MOMENTUM_WS_REPLAY_LIMIT` | `500` | |
| `MOMENTUM_FORMS_IP_HASH_SALT` | `dev-only-change-me` | Salts the public form endpoint's rate-limit hash of a submitter's IP (S4.2.1); the raw IP is never stored. Must be set (not the dev default) in production, like `MOMENTUM_SECRET_KEY` |
| `MOMENTUM_FORMS_RATE_LIMIT_PER_IP` | `5` | Submissions one (form, hashed IP) pair may make inside the rolling window |
| `MOMENTUM_FORMS_RATE_LIMIT_PER_FORM` | `60` | Submissions one form may receive in total inside the rolling window, regardless of IP (bounds a spoofed-IP flood) |
| `MOMENTUM_FORMS_RATE_LIMIT_WINDOW_MINUTES` | `10` | The rolling window both limits above are counted over |
| `MOMENTUM_TRUSTED_PROXY_HOPS` | `0` | S5.0.2: how many reverse proxies in front of the app append to `X-Forwarded-For` (Azure App Service: `1`). Rate limits take the client address that many entries from the right, so a visitor can't forge it; `momentum serve` trusts forwarded headers only when this is above 0. `0` = the connection's own address |

## Storage

| Setting | Default | Description |
|---|---|---|
| `MOMENTUM_STORAGE_BACKEND` | `local` | `local` · `azure_blob` |
| `MOMENTUM_STORAGE_LOCAL_DIR` | `./.data/files` | |
| `MOMENTUM_AZURE_BLOB_ACCOUNT_URL` / `_CONTAINER` / `_CONNECTION_STRING` | | Phase 8; managed identity if no connection string |
| `MOMENTUM_MAX_UPLOAD_MB` | `50` | |

## AI

| Setting | Default | Description |
|---|---|---|
| `MOMENTUM_AI_ENABLED` | `true` | Master switch (UI hides AI when false) |
| `MOMENTUM_LLM_MODE` | `mock` (local/test) | `gateway` · `mock` · `record` (record real responses to fixtures). Production requires `gateway` while AI is enabled (startup fails otherwise: never a silent mock fallback) |
| `MOMENTUM_LLM_BASE_URL` | `http://localhost:4000/v1` | Any OpenAI-compatible gateway (LiteLLM, Portkey, …) |
| `MOMENTUM_LLM_API_KEY` | | Gateway key (LiteLLM virtual key, Portkey API key, …). Never printed by `llm-check` |
| `MOMENTUM_LLM_API_KEY_HEADER` | `Authorization` | Header that carries the key. `Authorization` sends `Bearer <key>`; any other name (e.g. `x-portkey-api-key`) sends the raw key in that header |
| `MOMENTUM_LLM_EXTRA_HEADERS` | `{}` | JSON object of extra **non-secret** headers on every gateway call (e.g. a provider/config routing header). Validated at startup |
| `MOMENTUM_LLM_MODEL_FAST` | `claude-fast` | Model names as the gateway knows them (a LiteLLM alias, or a Portkey `@provider/model` id) |
| `MOMENTUM_LLM_MODEL_DEFAULT` | `claude-default` | |
| `MOMENTUM_LLM_MODEL_SMART` | `claude-smart` | |
| `MOMENTUM_LLM_EMBED_MODEL` | `cohere-embed-v3` | |
| `MOMENTUM_LLM_EMBED_DIM` | `1024` | Must match the `vector(n)` column |
| `MOMENTUM_LLM_EMBED_BATCH` | `96` | |
| `MOMENTUM_LLM_TIMEOUT_S` | `60` | |
| `MOMENTUM_LLM_MAX_RETRIES` | `2` | |
| `MOMENTUM_LLM_SUPPORTS_STREAMING_TOOLS` | `true` | Fall back to non-streaming tool steps if false |
| `MOMENTUM_LLM_RERANK_MODEL` | `cohere-rerank-v3.5` | Rerank model name as the gateway knows it (Cohere-style `/rerank`). Probed by `llm-check`. For cost estimates, its `LLM_PRICE_TABLE` `in_per_mtok` is the price per search unit |
| `MOMENTUM_AI_RERANK` | `false` | Rerank hybrid-search candidates before the top k (S3.1.4). Turn on once `llm-check`'s rerank row passes |
| `MOMENTUM_LLM_PRICE_TABLE` | `{}` | JSON `{model: {in_per_mtok, out_per_mtok}}` (USD, keyed by the configured model name) for cost estimates; unlisted models cost 0. **Set it in gateway mode:** with no entry the admin usage page shows "cost isn't measured", `llm-check` warns (`pricing` row) and startup logs `budget_unpriced` if a budget is set |
| `MOMENTUM_LLM_FIXTURES_DIR` | (packaged) | Mock/record fixture directory; empty = `momentum/ai/evals/fixtures/mock_responses` |
| `MOMENTUM_EVALS_DATABASE_URL` | (empty) | S3.5.1: the throwaway database `momentum evals` drops and rebuilds on every run (migrate, seed, eval workspace, reindex). Its name must end in `_evals`. Empty = the main database's name + `_evals` on the same server (the role needs `CREATEDB`) |
| `MOMENTUM_AI_MONTHLY_BUDGET_USD` | `0` (= unlimited) | Workspace cap on estimated cost (sum of `llm_calls.cost_usd` since 00:00 UTC on the 1st); checked before every call. Only models priced in `MOMENTUM_LLM_PRICE_TABLE` count, so an unpriced model never trips it (the usage page, `llm-check` and the startup log say so) |
| `MOMENTUM_SECURITY_HEADERS` | `true` | S7.5.2: CSP, `nosniff`, Referrer-Policy, Permissions-Policy, COOP, frame options and (in production) HSTS on every response (`core/http.py`). A host that embeds Momentum and sets its own headers can turn this off |
| `MOMENTUM_FRAME_ANCESTORS` | `'self'` | Who may show Momentum's pages in a frame (CSP `frame-ancestors` sources, e.g. `'self' https://host.example`); `'none'` forbids framing |
| `MOMENTUM_CONTENT_SECURITY_POLICY` | (empty) | Replaces the default page CSP entirely (an embedding host with other script origins); empty = the default (`docs/engineering/security.md`) |
| `MOMENTUM_AI_USER_CALLS_PER_HOUR` | `200` | Phase 7: one person's own successful model calls in a rolling hour (agent runs have their own budgets); the next call answers 429 `ai_rate_limited`. A chat turn with tools makes a few calls, so 200 is ~40 busy turns an hour. `0` = unlimited |
| `MOMENTUM_AGENTS_ENABLED` | `true` | Kill switch for agents: nothing is scheduled, triggered or run while false (agents stay editable; events meanwhile are skipped, not replayed). The AI master switch and each agent's own `enabled` apply too (S5.1.2) |
| `MOMENTUM_AGENT_EXTENSIONS` | `""` | A host's agent extensions, `"package.module:attribute"` (an `Extensions` object or a function returning one): extra AI tools, handler agents, agent definition directories (S5.1.5, ADR-0009, INTEGRATION_GUIDE §6.7). Set it for the web app **and** the worker |
| `MOMENTUM_AGENT_MAX_STEPS` | `15` | Ceiling on model steps per agent run (1–50). An agent's own `limits.max_steps` may be lower, never higher (S5.1.1) |
| `MOMENTUM_AGENT_TIMEOUT_S` | `300` | Ceiling on an agent run's wall-clock time in seconds (10–3600). An agent's own `limits.timeout_s` may be lower, never higher (S5.1.1) |
| `MOMENTUM_AI_AUTO_APPLY_LOW_RISK` | `false` | Workspace default for ⌘K/chat |
| `MOMENTUM_AI_DEBUG_CAPTURE` | `false` | Store prompts/responses for 7 days (never in prod by default) |

## Planning (Phase 6)

| Setting | Default | Description |
|---|---|---|
| `MOMENTUM_WORKLOAD_DEFAULT_HOURS` | `30` | Weekly hours a person can plan against when neither they nor a workspace admin has set one (0–80). Admins override it per workspace (`workspaces.settings['workload']`), people per themselves (`users.prefs['weekly_hours']`) and per week (`capacity`, e.g. time off). Used by the Workload view and Architect's capacity notes (S6.4.1) |
| `MOMENTUM_FORECAST_RUNS` | `10000` | Monte Carlo runs per project forecast (100–200,000). About 0.2 s per project at the default (pure Python) (S6.5.3) |
| `MOMENTUM_FORECASTS_ENABLED` | `true` | The nightly forecast job's kill switch (`compute_forecasts`, nightly at 02:30 on the worker's clock). When off, a forecast can still be refreshed from a project's overview (S6.5.3) |

## Integrations (Phase 9)

| Setting | Description |
|---|---|
| `MOMENTUM_SLACK_ENABLED`, `_SLACK_BOT_TOKEN`, `_SLACK_SIGNING_SECRET`, `_SLACK_APP_TOKEN` (Socket Mode, local) | Slack app |
| `MOMENTUM_GRAPH_ENABLED`, `_GRAPH_TENANT_ID`, `_GRAPH_CLIENT_ID`, `_GRAPH_CLIENT_SECRET` | Outlook calendar |
| `MOMENTUM_EMAIL_IN_ENABLED`, `_EMAIL_IN_DOMAIN` | Email-to-task |
| `MOMENTUM_EMAIL_OUT_BACKEND` (`none`,`smtp`,`acs`) + SMTP settings | Outbound email |
| `MOMENTUM_ASANA_BASE_URL` | Asana's API (`https://app.asana.com/api/1.0`); the e2e run points it at `tools/e2e/asana_fixture_server.py`. The importer is always available to admins and members who can create teams; its token is entered per import and never stored (the CLI `momentum asana-import` reads it from `ASANA_PAT`, an environment variable of that one command, not a setting) |

## Observability

| Setting | Default | Description |
|---|---|---|
| `MOMENTUM_OTEL_ENABLED` | `false` | |
| `MOMENTUM_APPLICATIONINSIGHTS_CONNECTION_STRING` | | Phase 8 (Azure Monitor exporter) |
| `MOMENTUM_SENTRY_DSN` | | Optional alternative |

## Frontend runtime config (`GET /api/v1/config`, unauthenticated-safe subset)

`{ base_path, ai_enabled, auth: {mode, login_url, logout_url}, features: {slack, calendar, import, agents, goals, …}, version, env }`
