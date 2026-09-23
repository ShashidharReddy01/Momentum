# ADR-0008: AI actions follow preview → confirm → apply → undo
- **Status:** Accepted · **Date:** 2026-09-23
## Decision
AI never mutates data directly. Write tools produce dry-run previews (SAVEPOINT + rollback). Applying runs all operations in one transaction under one activity batch, after a version stale check. Autonomy (suggest/confirm/auto) × risk (read/low/medium/high) decides whether a proposal needs a human. Everything AI-applied is attributed (`created_via`, `ai_action_id`) and undoable.
## Consequences
Trust and safety by construction; slightly more latency for write flows; requires every service mutation to support dry-run and undo payloads (enforced by the Definition of Done).
