# ADR-0002: Postgres-only infrastructure
- **Status:** Accepted · **Date:** 2026-09-23
## Context
Minimize Azure resources and moving parts; need a job queue, realtime fan-out, full-text and vector search.
## Decision
PostgreSQL 16 for data + `tsvector`/`pg_trgm` search + `pgvector` + Procrastinate job queue + `LISTEN/NOTIFY` for realtime fan-out. No Redis.
## Alternatives
Redis + arq/Celery (another service to run); a dedicated vector DB (unneeded at this scale); Azure Service Bus (vendor lock-in, heavier).
## Consequences
One stateful dependency to back up and move. NOTIFY payload limits → we send ids and load rows. Revisit if job volume grows by orders of magnitude.
