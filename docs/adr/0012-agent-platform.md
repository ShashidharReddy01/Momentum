# ADR-0012: Agent platform (packs, durable jobs, asks, records, skills, coordination)

- **Status:** Accepted
- **Date:** 2026-10-08
- **Deciders:** product owner, AI (drafted)

## Context
Phase 5 gave Momentum agents as users with triggers, budgets and autonomy, run as LLM loops or host handlers (ADR-0009). Each run is one transaction with one timeout: it cannot pause, ask a person something, survive a restart, or split work across children. Agents never trigger other agents (loop protection). There is no reviewable structured output beyond `agent_runs.output`, no capability directory, and no way for several agents to work on one piece of work together.

The product owner wants Momentum to host **50–100+ agents** for many kinds of work (invoices, contracts, onboarding, RFPs, data clean-ups, compliance checks), with the first being Bernie, an invoice agent (ADR-0013). Building Bernie directly on Phase 5's primitives would mean every future agent re-invents durability, structured results, memory and coordination. The design (`docs/superpowers/specs/2026-10-06-phase-7-6-agent-platform-bernie-design.md`) instead sizes a **general platform** against a table of 14 example future packs (spec §1.1) before writing Bernie, so later agents cost only their own logic.

## Decision
Nine building blocks (spec §1), each with its own section below and its own migration:

1. **Packs** (§3): one agent's folder (manifest, code, prompts, record types, settings, starter skills, evals, tests), loaded from the `momentum.packs` entry-point group. A pack imports only `momentum.sdk` — never `momentum.domain`, `momentum.ai`, `momentum.agents`, `momentum.core` or `momentum.files` directly — enforced by import-linter, one contract per pack.
2. **`momentum.sdk`** is the only thing a pack imports from Momentum: a versioned facade (`SDK_VERSION`) over jobs, asks, records, entities, skills, settings, policy, effects, files, consult and testing. With 100 packs, Momentum's internals must stay free to change; only the SDK is a promise.
3. **Durable jobs** (§4): **durable execution by replay** (the pattern used by Temporal, DBOS and Azure Durable Functions), implemented on Postgres only, consistent with ADR-0002's "fewer moving parts" stance — no new queue or workflow engine dependency. A step runs once (`job.step(key, fn, *args)`); writes happen only inside steps through `job.effects.*`; waiting (`job.ask`, `job.gather`, `job.sleep_until`, `job.wait_for_event`) raises `Suspend`, which the engine turns into `status='waiting'` and a freed worker; the next claim replays finished steps instantly and continues from where it left off. Child jobs (`job.spawn`/`job.gather`) let one parent (e.g. a batch of invoices) fan out and fan back in.
4. **Asks** (§5): a job's question to a person — choice, confirm, form or text — with evidence, routing, reminders and an expiry default every pack must declare. Answered in the ask card, the inbox, or by replying in the thread (interpreted against the ask's schema, applied only when certain).
5. **Records** (§6): a typed, versioned, reviewable result (e.g. `invoice`), validated against the owning pack's JSON Schema on every write, edited only through auditable, learnable **correction operations** (`set`, `add_item`, `distribute`, …), with per-field provenance and confidence.
6. **Entities and skills** (§7): what a pack knows across records (e.g. a vendor) and what it learned about them. A skill is **proposed** by a pack after a person's correction, **tried out** automatically against the approved record and nearby ones, then **decided** by a person (approve, edit-and-approve, reject) before it's ever used live. No free-form "agent memory" text store — everything remembered is a typed, reviewable row.
7. **Coordination** (§10): **Mo is the coordinator.** Work needing several agents becomes a **plan** a person confirms; steps hand off only through records, never chat. A confirmed plan is the **one exception** to "agents never trigger agents" (D5) — the plan engine, not one agent calling another, queues the next step. `job.consult(capability, input)` lets a pack ask another pack's read-only, consultable capability synchronously, at depth 1, with no effects, billed to the caller.
8. **Governance** (§8): a manifest's declared `effects` are the only writes a job may make — **handing an agent work is consent to those effects** (D8); anything else is `job.propose(...)`, the existing preview → confirm → apply → undo flow. A policy engine (`Policy`/`Rule`, ordered, deterministic, no model) decides allow / require_human / hold / deny per record, with every rule's fired-or-not result stored for "why?". Data classification (`public`/`internal`/`financial`/`personal`) drives guest visibility, trace redaction and export permissions. A regex-and-checksum scrubber (no model) blocks a learned skill, or a trace, from carrying a value, email, IBAN or card number; it is fail-loud.
9. **Builder kit** (§11): `momentum packs new/check/run/eval`, so agent #2 costs only its own logic, plus the generic **review screen kit** (§12.4) — one two-pane (document + form) UI for every record type, so a pack needs no custom review screen.

Agent descriptions are shaped like **A2A v1.0 Agent Cards**, and job states map one-to-one onto A2A task states (D12), so agents outside Momentum could be hosted later. The A2A protocol itself is not served in this phase — futureproofing, not a commitment.

**No new runtime dependency, no system package, synthetic data only (D10)** — CLAUDE.md's standing rules, continuing the "pure pip wheels, no system packages" discipline ADR-0011 applied to Phase 7.5's file dependencies. D10 adds "no AGPL" explicitly for this phase, because the invoice-pipeline notebook this phase ports leans on PyMuPDF (AGPL) and Tesseract (a system package); see ADR-0013.

## Alternatives considered
| Option | Pros | Cons |
|---|---|---|
| Build Bernie directly on Phase 5 runs (one transaction, no pause) | Smallest change | No pausing for a person, no batches, no memory; every later agent hits the same wall and re-solves it alone |
| A third-party workflow engine (Temporal, Airflow) for durable jobs | Battle-tested | A new infrastructure dependency and operational surface, against the project's "fewer moving parts" stance (ADR-0002); Postgres-only replay already fits the scale target |
| Free-form agent memory (a text store an agent appends to) | Simple to build | Unreviewable, ungoverned, and not learnable in the structured sense D7 asks for; rejected in favour of typed, reviewable records, entity profiles and skills |
| Packs as user-uploaded scripts with a sandbox | Lets non-developers add agents | Explicitly out of scope (D2): packs are developer-written, code-reviewed, deployed with Momentum, for now |
| Let any agent call any other agent directly | Simpler mental model | Breaks loop protection; D5 keeps that invariant and makes the plan engine the one, auditable, person-confirmed exception |

## Consequences
- **Positive:** Bernie (ADR-0013) is the only agent built as a feature; every future pack in the spec's 14-row table (§1.1) is buildable from these nine blocks with no platform change. Durability, memory and coordination are solved once. Every automated write stays visible, budgeted, killable and undoable, same as Phase 5.
- **Negative:** this is the larger half of the phase before any invoice is ever read — a real platform investment ahead of its second user. The replay model requires packs to follow determinism rules (no direct `datetime.now()`/`uuid4()`/`random.` outside steps), enforced by a lint test, which is a new constraint pack authors must learn.
- **Follow-ups:** `docs/ai/agents.md` gains a "Packs and jobs" section; `docs/agents/` is new (README, building-a-pack guide, SDK reference, porting-a-notebook guide, the pack catalogue, Bernie's user/admin doc). INTEGRATION_GUIDE gains a packs section at phase exit. `docs/agents/pack-catalogue.md` is kept up to date whenever a future pack idea comes up (spec §1.1).
- **Reversal:** `MOMENTUM_PACKS_ENABLED=false` pauses every pack's jobs without touching legacy (`mode='oneshot'`) agents, which are untouched by this ADR. Removing a pack's entry point stops it loading; its tables and records stay, inert.
