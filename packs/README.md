# Packs: agents on the Momentum platform

A **pack** is one agent's whole implementation: a manifest, its durable job, prompts, record and
entity types, settings, starter skills, evals and tests — one folder here, one installed Python
package. The platform under packs is `momentum.agents` (loader, durable jobs, asks, plans) and
`momentum.domain` (records, entities, skills); see ADR-0012 and
`docs/superpowers/specs/2026-10-06-phase-7-6-agent-platform-bernie-design.md`.

**A pack imports only `momentum.sdk`.** Never `momentum.domain`, `momentum.ai`, `momentum.agents`,
`momentum.core` or `momentum.files` directly — import-linter enforces this per pack, and
`momentum packs new` scaffolds the contract for you. With 100+ packs, Momentum's internals must
stay free to change; only the SDK is a promise (versioned, `momentum.sdk.SDK_VERSION`).

## What's here

| Pack | Status | What it does |
|---|---|---|
| [`bernie/`](bernie/) | Phase 7.6 | Reads invoices, checks every number, asks when unsure, routes for approval (ADR-0013) |

## Building a pack

See `docs/agents/building-a-pack.md` (written in S76-13) for the full guide, `momentum packs new`
to scaffold one, and `docs/agents/pack-catalogue.md` for the future-pack ideas the platform is
sized against. Real documents and credentials never enter this repo — packs are tested against
synthetic data generated at test time (CLAUDE.md: synthetic data only).
