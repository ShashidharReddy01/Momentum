# ADR-0003: Pluggable authentication with Easy Auth in production
- **Status:** Accepted · **Date:** 2026-09-23
## Context
Production uses Azure App Service Authentication (Easy Auth, Entra ID). Development is local-only until Phase 9. Momentum may later be embedded in a host app with its own auth.
## Decision
An `AuthProvider` interface with modes `dev`, `easyauth-sim`, `easyauth`, `oidc`, `host`, plus API tokens. Users are keyed by internal UUID + email, with provider identities linked in `user_identities` (re-link by email on tenant moves). Easy Auth headers are trusted only when running on App Service.
## Consequences
The same code runs in all environments; the real Easy Auth parser is exercised locally via the simulator. Header trust is guarded to prevent spoofing outside App Service.
