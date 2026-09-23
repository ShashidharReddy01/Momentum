# ADR-0006: Embeddable module design
- **Status:** Accepted · **Date:** 2026-09-23
## Context
Momentum may be "lifted and plugged into a different project".
## Decision
Backend: `create_app()` and `mount_momentum(host_app, settings, resolve_principal)`, no import-time side effects, `MOMENTUM_` env prefix, dedicated Postgres schema (incl. Alembic and Procrastinate tables), prefixed NOTIFY channel, base-path-aware URLs, `workspace_id` on all rows. Frontend: `src/momentum` module exporting `MomentumApp`/`MomentumProvider`/`momentumRoutes`, basePath-aware links, providers created per mount, styles scoped to `.momentum-root` in a CSS layer; Tailwind preflight scoped. If a host's CSS conflicts, enable the Tailwind `prefix(mo)` build variant (documented fallback).
## Consequences
Slight extra discipline everywhere; portability tests guard it in `make check`.
