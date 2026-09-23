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
| AI | OpenAI-compatible gateway (LiteLLM) with model aliases | `apps/api/momentum/ai` (Phase 3+) |
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
Any OpenAI-compatible endpoint: set `MOMENTUM_LLM_BASE_URL`, `MOMENTUM_LLM_API_KEY`, and map the aliases (`fast`, `default`, `smart`, `embed`). Run `momentum llm-check`.

### 6.5 Look and feel
Design tokens in `apps/web/src/momentum/styles/tokens.css` (scoped). To match a host brand, override the token values; component code never contains raw colors.

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

---

## 8. Change log

| Date | Phase | Integration-relevant change |
|---|---|---|
| 2026-09-23 | 0 | Initial: `create_app`, `mount_momentum` + `momentum_lifespan`, `host` auth mode, schema-scoped migrations and job queue, embeddable `MomentumApp` with `basePath`, scoped styles |
| 2026-09-23 | 1 | Migrations 0002-0006 in the `momentum` schema (teams, projects, sections, tasks, followers, comments, mentions, reactions, per-user My Tasks placements); all new API under `/api/v1` (`/home`, `/me/tasks`, `/me/prefs/views/*`, `/tasks/*`, `/comments/*`, `/mentions/search`, `/undo`). UI stores only per-device conveniences in `localStorage` under the `momentum.` prefix (drafts, collapsed sections, last quick-add project). Responsive shell: below 900px the sidebar is a drawer and panes go full-screen, so a host page embedding the UI should give it the full viewport width. E2E journeys runnable in the host via `make e2e` (V9). |
