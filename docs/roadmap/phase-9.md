# Phase 9: Azure Deployment and Go-Live

**Goal:** Momentum running in the office Azure environment behind Easy Auth (Entra ID), using the office LiteLLM (Bedrock Claude + Cohere v3), with the team's Asana data imported. Milestone **M5**.

**Read first:** architecture/embedding-and-portability.md §3, architecture/configuration.md, architecture/auth-and-permissions.md §2.

**Kickoff prerequisites (ask IT early, ideally during Phase 7):** allowed region(s); App Service + PG Flexible approval; VNet/private endpoint requirements; who creates the Entra app registration and app role `Momentum.Admin`; LiteLLM endpoint, virtual key, model aliases, and network reachability from App Service; registry choice (ACR); CI system (GitHub Actions or Azure DevOps).

**Exit criteria:** go-live checklist complete; the team logs in via Entra; Asana import done; backups verified; rollback tested once (slot swap back).

---

## E9.1 Azure adapters

| Slice | Scope | AC | Size |
|---|---|---|---|
| S9.1.1 Blob storage | `storage/azure_blob.py` (SAS upload/download URLs, managed identity or connection string), Azurite in compose for tests; `momentum migrate-files --from local --to azure_blob` | All attachment tests pass against Azurite | M |
| S9.1.2 Telemetry | Azure Monitor OpenTelemetry exporter enabled by setting; custom metrics (AI tokens/cost, job failures, WS connections) | Traces visible in App Insights (verified in env) | S |
| S9.1.3 Office LiteLLM check | Run `momentum llm-check` against the office gateway from an App Service console or a pipeline job; tune `LLM_SUPPORTS_STREAMING_TOOLS`, timeouts, price table; run `EVALS_LIVE=1 make evals` | All checks pass; eval thresholds met | S |

## E9.2 Infrastructure as code

| Slice | Scope | Size |
|---|---|---|
| S9.2.1 Bicep core | `infra/bicep/main.bicep` + modules: App Service plan (Linux), Web App for Containers (Always On, Web sockets, health check `/healthz`, staging slot, app settings with Key Vault references, managed identity), PostgreSQL Flexible Server (PG16, `azure.extensions` = `VECTOR,PG_TRGM,CITEXT`, backups, firewall/private access per policy), Storage account + container, Key Vault, Log Analytics + App Insights, ACR; parameter files `office.bicepparam` (+ `rehearsal.bicepparam`) | M |
| S9.2.2 Easy Auth config | `authsettingsV2`: Entra ID provider (client id, tenant issuer), `unauthenticatedClientAction: Return401` with `excludedPaths` (`/healthz`, `/api/v1/config`, `/api/public/*`, `/f/*`, `/webhooks/*`, `/mcp`), token store on, allowed audiences; SPA login redirect handled by the app | S |
| S9.2.3 Networking (optional) | VNet integration, private endpoints for PG/Storage/Key Vault, outbound to LiteLLM and Slack allowed | M |

## E9.3 Pipeline and go-live

| Slice | Scope | Size |
|---|---|---|
| S9.3.1 CI/CD | Pipeline: `make check` → build image (tag = git sha) → push to ACR → deploy to staging slot → run migrations (release step with advisory lock) → smoke tests (`momentum smoke`) → manual approval → swap | M |
| S9.3.2 Runbooks | `docs/runbooks/deploy.md`, `rollback.md` (swap back; migrations are backward-compatible via expand/contract), `backup-restore.md` (PITR), `lift-and-shift.md`, `incident.md` (AI kill switch, disable agents, read-only mode) | S |
| S9.3.3 Go-live | Configure prod settings; install the Slack app for the prod URL; seed workspace (no synthetic data); admins bootstrap; run the Asana importer against the real workspace; invite users; hypercare checklist for week 1 (daily error review, AI cost check, feedback channel) | M |

## Go-live checklist
- [ ] Settings reviewed (`MOMENTUM_ENV=production`, no dev auth, `SECRET_KEY` from Key Vault)
- [ ] Easy Auth on; direct access without login returns 401; excluded paths behave as expected
- [ ] `momentum smoke` passes on the production URL
- [ ] Backup PITR enabled; a restore test was done in the rehearsal environment
- [ ] AI budget set; agents enabled deliberately (start with Pulse + Herald in confirm mode)
- [ ] Slack app installed; digest test received
- [ ] Asana import verified by project owners (spot-check counts)
- [ ] Feedback channel announced; STATUS updated with the go-live date
