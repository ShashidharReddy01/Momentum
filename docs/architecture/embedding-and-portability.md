# Embedding and Portability

Momentum must support three futures without rework:

1. **Standalone:** its own App Service, its own domain (the default).
2. **Lift-and-shift:** the same standalone app moved to another environment/tenant (e.g., office Azure).
3. **Plug-in:** Momentum mounted *inside another project*: its backend routes in a host FastAPI app, its UI inside a host React app, and its tables in a host Postgres database.

## 1. Backend: package and mounting

`momentum` is an installable Python package (`apps/api`, `pyproject.toml`, name `momentum`).

```python
# Standalone
from momentum import create_app, Settings
app = create_app(Settings())

# Plug-in to a host FastAPI app
from momentum import mount_momentum, Settings
from momentum.auth import Principal

async def host_principal(request) -> Principal | None:
    user = request.state.user          # host's own auth
    return Principal(provider="host", subject=str(user.id), tenant_id=None,
                     email=user.email, name=user.name, roles=tuple(user.roles), raw_claims={})

mount_momentum(host_app, settings=Settings(base_path="/momentum", auth_mode="host",
               serve_spa=False, worker_mode="separate"),
               resolve_principal=host_principal)
```

`mount_momentum` builds a Momentum sub-application (`FastAPI()` mounted at `base_path`) with its own lifespan (engine, worker, WS hub). It never modifies the host's middleware, exception handlers, or OpenAPI.

**Rules that make this possible**

| Rule | Why |
|---|---|
| No import-time side effects (no engine/settings creation at import) | Hosts import without starting anything |
| All state on `app.state.momentum` (a `MomentumRuntime` object) | No globals colliding with the host |
| Env prefix `MOMENTUM_` | No config collisions |
| Postgres schema `MOMENTUM_DB_SCHEMA` + own Alembic version table | Coexists in a host database |
| Job queue: Procrastinate tables in the Momentum schema, queue names prefixed `momentum_` | Coexists with host workers |
| NOTIFY channel `momentum_events` (prefixed) | |
| All URLs built with `base_path` | Mountable under a sub-path |
| Auth via `AuthProvider` (`host` mode uses the host's session) | Single sign-on inside the host |
| Users keyed by internal UUID + email; identities linkable | Host user ids map cleanly |
| Every table has `workspace_id` | A host with multiple tenants can map tenant ↔ workspace |
| Logging via `structlog` with a `momentum` logger namespace | Host log config applies |

## 2. Frontend: app and embeddable module

The frontend is structured so the **Momentum UI can be mounted inside another React app**:

```
apps/web/src/
├── main.tsx                 # standalone bootstrap (createRoot + <MomentumApp/>)
├── momentum/                # everything else lives here: the embeddable module
│   ├── index.ts             # export { MomentumApp, MomentumProvider, momentumRoutes, type MomentumConfig }
│   ├── MomentumApp.tsx
│   ├── routes.tsx
│   └── … features, components, lib, styles
```

```tsx
// Host usage (React Router 7 in the host)
import { MomentumProvider, momentumRoutes } from '@momentum/web';
<MomentumProvider config={{ basePath: '/momentum', apiBase: '/momentum/api/v1', auth: 'host' }}>
  {/* host renders momentumRoutes under its router at /momentum/* */}
</MomentumProvider>
```

| Rule | How |
|---|---|
| No hard-coded absolute paths | `useMomentumConfig().basePath`, relative API base |
| Styles don't leak | Design tokens are scoped to `.momentum-root` (`[data-momentum]`); Tailwind utilities are generated in a `@layer momentum`; **preflight is scoped** to `.momentum-root` via the design-system reset (Tailwind's global preflight is disabled when `embedded: true` in the build). An optional Tailwind `prefix(mo)` build variant is documented in ADR-0006 if a host conflict is found. |
| No global singletons | QueryClient, Zustand stores, and the WS client are created inside `MomentumProvider` |
| Fonts self-hosted | `@fontsource-variable/*` packages, loaded by Momentum's CSS; no external CDN |
| Portals | Radix portals render into a `.momentum-root` container, so tokens apply to menus/dialogs |
| Router-agnostic links | Use the module's `<MLink>` wrapper around React Router `Link`, respecting `basePath` |

## 3. Lift-and-shift checklist

1. Same image, new settings (see `configuration.md`).
2. New Entra tenant? `MOMENTUM_IDENTITY_LINK_BY_EMAIL=true` re-links users by email on first login.
3. Data: `momentum export --out bundle.zip [--with-files]` → `momentum import bundle.zip` (versioned JSON; ids preserved) **or** `pg_dump -n momentum` / `pg_restore`.
4. Files: copy the storage container (AzCopy) or use the bundle with files.
5. Embeddings: if the embedding model/dimension differs → `momentum reindex`.
6. LLM: point `MOMENTUM_LLM_BASE_URL` at the new gateway; map aliases; run `momentum llm-check`.
7. Integrations: re-create the Slack app/credentials for the new URL; update the Graph app registration.
8. Smoke test: `momentum smoke --base-url …` (login redirect, /healthz, /api/v1/config, WS connect).

## 4. Portability tests (in `make check`)

- `tests/portability/test_mount.py`: mounts Momentum under `/momentum` in a dummy host FastAPI app with `host` auth, and runs a create-project → create-task flow.
- `tests/portability/test_schema.py`: migrations run into a non-default schema name (`momentum_alt`) with no objects created in `public`.
- `apps/web` test: renders `<MomentumApp>` inside a host wrapper with `basePath="/x"`, and asserts links and API calls are prefixed.
