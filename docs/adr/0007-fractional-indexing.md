# ADR-0007: Fractional indexing for ordering
- **Status:** Accepted · **Date:** 2026-09-23
## Decision
Ordered collections (sections, tasks within sections, subtasks, My Tasks buckets, favorites) use string fractional keys (`position text collate "C"`), generated with `key_between(before, after)`. A rebalance job rewrites keys for a container when any key exceeds 32 characters.
## Alternatives
Integer positions with renumbering (write amplification, conflicts); linked lists (hard to query).
## Consequences
O(1) writes per move, stable under concurrent inserts (with a random jitter suffix to avoid collisions).
