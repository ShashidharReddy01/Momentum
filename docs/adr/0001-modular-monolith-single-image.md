# ADR-0001: Modular monolith, single image, SPA served by FastAPI
- **Status:** Accepted · **Date:** 2026-09-23
## Context
10–15 users, one builder, a lift-and-shift to Azure App Service, and Easy Auth protecting everything with a same-origin cookie.
## Decision
One Python package and one container image that serves API, WebSockets, SSE, MCP, webhooks, and the built React SPA. Internally modular (domain modules with strict layering).
## Alternatives
Separate frontend hosting (Static Web Apps) + API: more infra, CORS and auth token plumbing. Microservices: unjustified at this scale.
## Consequences
Simple deploys and auth. Modules must stay disciplined (import-linter). If embedded in a host, `MOMENTUM_SERVE_SPA=false` and the host serves the UI module.
