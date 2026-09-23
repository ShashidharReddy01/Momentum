# Phase 0: Foundations

**Goal:** a runnable, testable, portable skeleton. `make dev` boots Momentum locally; you log in via dev mode *and* the Easy Auth simulator; the shell renders with the Momentum design language; `make check` is green.

**Exit criteria**
- [ ] `make dev` starts Postgres (+pgvector) and the API (reload) + web (Vite) with a proxy
- [ ] Dev login and easyauth-sim login both work and show your name in the shell
- [ ] `make check` green (ruff, mypy, import-linter, pytest, eslint, tsc, vitest)
- [ ] Production Docker image builds and serves SPA + API on one port locally
- [ ] Portability tests (mount under base path, non-default schema) pass
- [ ] STATUS updated; ADRs 0001–0008 accepted

---

## E0.1 Repository and tooling

### S0.1.1: Monorepo scaffold
**Goal:** a clean repo layout with backend and frontend skeletons.
**Read first:** architecture/overview.md §2, frontend/frontend-architecture.md §3, embedding-and-portability.md.
**Backend:** `apps/api` with `pyproject.toml` (uv; deps: fastapi, uvicorn[standard], gunicorn, sqlalchemy[asyncio], psycopg[binary], alembic, pydantic, pydantic-settings, structlog, typer, itsdangerous, uuid-utils, httpx; dev: pytest, pytest-asyncio, testcontainers, ruff, mypy, import-linter, time-machine). Package `momentum/` with `__init__.py` exporting `create_app`, `mount_momentum`, `Settings` (lazy). `app.py` with `create_app()` returning FastAPI with `/healthz` and `/api/v1/config`. `cli.py` (Typer): `serve`, `migrate`, `worker` (stub), `seed` (stub).
**Frontend:** `apps/web` (pnpm) with Vite + React 19 + TS strict, alias `@` → `src/momentum`, `src/main.tsx` + `src/momentum/index.ts`, `MomentumApp` rendering "Momentum". ESLint + Prettier configured.
**Root:** `Makefile`, `.editorconfig`, `.gitignore`, `.env.example`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/` (this pack), `.pre-commit-config.yaml` (ruff, prettier, end-of-file).
**AC**
- [ ] `uv run momentum serve` → `GET /healthz` returns `{"status":"ok"}`
- [ ] `pnpm -C apps/web dev` renders the app
- [ ] `import momentum` has no side effects (test)
**Tests:** `test_healthz`, `test_import_no_side_effects`, web smoke render test.
**Size:** M

### S0.1.2: Dev environment and Docker image
**Goal:** one command local dev; one production image.
**Build:** `infra/compose/docker-compose.dev.yml` with `postgres` (image `pgvector/pgvector:pg16`, init script creating schema `momentum` + extensions `vector`, `pg_trgm`, `citext`), optional `litellm` service (profile `ai`, config sample in `infra/litellm/config.example.yaml`). `make dev` runs compose + API (uvicorn reload) + Vite (proxy `/api`, `/ws`, `/dev`, `/auth` → :8000) concurrently. Multi-stage `infra/docker/Dockerfile`: stage 1 builds the web (`pnpm build`), stage 2 is Python slim + uv sync --frozen + copies `dist` → `momentum/web/static`; entrypoint `momentum serve` (gunicorn + uvicorn workers, `PORT` env honored). SPA fallback route serving `index.html`.
**AC**
- [ ] `make dev` works on a clean machine with Docker + uv + pnpm installed
- [ ] `docker build` + `docker run -p 8000:8000 --env-file .env` serves the SPA at `/` and the API at `/api/v1/config`
- [ ] Deep link `/projects/x` returns `index.html`
**Tests:** SPA fallback test; config endpoint test.
**Size:** M

### S0.1.3: Quality gate
**Goal:** `make check` as the single gate.
**Build:** ruff (lint+format check), mypy strict on `momentum/`, import-linter contracts (layering R1/R5/R6 from overview §3), pytest with testcontainers Postgres fixture (session-scoped container, per-test SAVEPOINT), eslint, `tsc --noEmit`, vitest, `make types` check (OpenAPI → `schema.d.ts` must be up to date). Optional git pre-push hook script.
**AC**
- [ ] `make check` runs everything and fails on any violation
- [ ] A deliberate layering violation is caught by import-linter (verified, then removed)
**Size:** S

### S0.1.4: Settings, logging, telemetry, errors
**Goal:** configuration and diagnostics foundations.
**Build:** `core/settings.py` (all Phase 0 settings from configuration.md, `MOMENTUM_` prefix, validation e.g. production requires SECRET_KEY and forbids dev auth); `core/telemetry.py` (structlog JSON/console, request-id middleware, OTEL disabled by default); `core/errors.py` (DomainError hierarchy + problem+json handlers); `core/ids.py` (uuid7).
**AC**
- [ ] Invalid combos fail at startup with a clear message (e.g., `ENV=production` + `AUTH_MODE=dev`)
- [ ] Every response has an `X-Request-ID`; errors return problem+json with `request_id`
**Tests:** settings validation matrix; error handler shapes.
**Size:** S

### S0.1.5: Database core and job queue
**Goal:** DB session/UoW, Alembic in-schema, Procrastinate wired.
**Build:** `core/db.py` (async engine, `search_path` = Momentum schema, `UnitOfWork` context manager with savepoint support for dry-run); Alembic env targeting `MOMENTUM_DB_SCHEMA` with the version table in the schema; first migration: `workspaces`, `users`, `user_identities`, `api_tokens`, `activity`, `events_outbox`, `idempotency_keys`; base mixins; `core/activity.py` and `core/events.py` skeletons (record + emit + NOTIFY after commit); Procrastinate app using the same DB/schema, `WORKER_MODE` handling in the lifespan, one periodic `heartbeat` job. `momentum seed` creates workspace "Acme Demo" + 12 synthetic users.
**AC**
- [ ] `make migrate` creates tables only in the `momentum` schema
- [ ] Migrations work with `MOMENTUM_DB_SCHEMA=momentum_alt` (portability test)
- [ ] The embedded worker runs the heartbeat job in dev
**Tests:** schema portability; UoW rollback; savepoint dry-run rollback; outbox + NOTIFY emitted after commit only.
**Size:** M

---

## E0.2 Identity (pluggable)

### S0.2.1: AuthProvider + dev mode + `/me`
**Read first:** architecture/auth-and-permissions.md.
**Build:** `auth/base.py` (Principal, AuthProvider protocol, `get_ctx` dependency); `auth/dev.py` (`GET /dev/login` returns JSON list of active seeded users; `POST /dev/login {user_id}` sets the signed cookie; `POST /dev/logout`); CSRF header check middleware for mutating requests; `GET /api/v1/me` → user + workspace + role; 401 problem+json includes `login_url`. Frontend: `features/auth` (`useMe`, boot gate, redirect to login URL on 401, session-expired banner), dev login page `/dev/login` listing users (avatar, name, role) with a purple "DEV" marker.
**AC**
- [ ] Unauthenticated SPA load redirects to `/dev/login`; picking a user lands on Home
- [ ] Dev mode refuses to start when `MOMENTUM_ENV=production`
- [ ] Mutations without `X-Requested-With: momentum` → 403
**Tests:** API auth tests; web boot-gate tests with MSW.
**Size:** M

### S0.2.2: Easy Auth provider + simulator
**Build:** `auth/easyauth.py` (decode `X-MS-CLIENT-PRINCIPAL` base64 JSON, claim mapping with configurable claim precedence, role extraction, tenant/domain allow-list, App Service guard via `WEBSITE_SITE_NAME` / `EASYAUTH_TRUST_HEADERS`), login/logout URLs (`/.auth/login/aad`, `/.auth/logout`); `auth/easyauth_sim.py` (dev middleware: reads the dev session, builds realistic principal JSON (oid, tid, preferred_username, name, roles) from seed data, injects headers, and serves `/.auth/login/aad` → dev picker and `/.auth/logout` locally). Sample principals in `tests/fixtures/easyauth/*.json`.
**AC**
- [ ] With `AUTH_MODE=easyauth-sim`, the full login flow works locally through the real parser
- [ ] `easyauth` mode refuses to start outside App Service unless explicitly overridden
- [ ] Client-supplied `X-MS-*` headers are ignored in `dev` mode
**Tests:** parser unit tests (claims variants, missing email, roles as list or claim entries), allow-list denial, guard behavior.
**Size:** M

### S0.2.3: Identity resolution and bootstrap admin
**Build:** `auth/identity.py` per auth doc §3 (lookup by identity → link by email → auto-provision → deny), bootstrap admins, admin-role sync, disabled users.
**AC**
- [ ] A user created under provider A logs in under provider B with the same email and keeps the same user id (lift-and-shift test)
- [ ] Non-allow-listed domains get 403 `not_invited`
**Tests:** full resolution matrix.
**Size:** S

### S0.2.4: Permissions skeleton
**Build:** `core/permissions.py` with the `Action` constants, `can`/`require`, workspace-role checks, and placeholders for project/task rules (completed in Phase 1). Test matrix scaffold.
**AC:** `require` raises `NotFound` vs `Forbidden` correctly per auth doc.
**Size:** S

---

## E0.3 App shell and design system

### S0.3.1: Design tokens, fonts, base components
**Read first:** frontend/design-system.md.
**Build:** `styles/tokens.css` (light + dark), `fonts.css` (@fontsource-variable Inter, Fraunces, JetBrains Mono; @fontsource Instrument Serif), `index.css` (Tailwind v4 import, `@theme` token mapping, `@layer momentum`, scoped base reset under `.momentum-root`); shadcn/ui init with our token names; primitives: Button, IconButton, Input, Tooltip, DropdownMenu, Dialog, Sheet, Tabs, Segmented, Kbd, Avatar, Skeleton, EmptyState, ErrorState, AICallout, AIBadge, MockBadge, Toast (sonner); `<Icon>` wrapper (lucide) and `<MoMark>`. A dev-only `/dev/ui` gallery page showing every component in light/dark.
**AC**
- [ ] Gallery renders all components in both themes; contrast of text tokens checked (documented table)
- [ ] No raw color literals in component code (lint rule active)
**Size:** M

### S0.3.2: Layout shell + routing + command palette skeleton
**Build:** `MomentumProvider` (config from `/api/v1/config`, QueryClient, theme, toasts, WS placeholder), React Router 7 routes (lazy placeholders for Home, My Tasks, Inbox, Ask, Project), `Layout` (Sidebar with sections from ux-specs §1, TopBar with breadcrumb, search trigger, Ask Mo toggle, bell, avatar menu with theme toggle + sign out), right-side panel hosts (TaskPaneHost, AskMoPanel placeholder), `CommandPalette` (cmdk) with navigation actions, keyboard shortcuts registry (`lib/keyboard.ts`) with `?` shortcut sheet. `basePath`-aware links (`MLink`).
**AC**
- [ ] Shell matches ux-specs §1; sidebar collapses (`⌘\`); `⌘K` opens palette; `⌘J` toggles the Mo panel
- [ ] Rendering `<MomentumApp basePath="/x">` prefixes all links and API calls (portability test)
**Tests:** shell render, keyboard shortcuts, basePath test.
**Size:** M

---

## Phase 0 backlog / notes
- Dark theme values are tuned in S0.3.1; they can be refined later.
- CI pipeline intentionally deferred to Phase 9 (local gate only).
