# Momentum Documentation Index

Docs are the **source of truth for intent**. Code must match them, and when the plan changes, the docs change in the same slice.

## Reading order for a new contributor (human or AI)

1. `../CLAUDE.md`: rules of engagement
2. `product/vision-and-scope.md`: what we're building and why
3. `architecture/overview.md`: the shape of the system
4. `process/ai-dev-workflow.md`: how work gets done
5. `progress/STATUS.md`: where we are now
6. `roadmap/phase-N.md` for the current phase

## Index

| Area | Document | Contents |
|---|---|---|
| Product | `product/vision-and-scope.md` | Vision, personas, principles, scope matrix, glossary |
| Product | `product/research/asana-analysis.md` | Background research on Asana (reference only) |
| Architecture | `architecture/overview.md` | Layers, modules, dependency rules, request lifecycle |
| Architecture | `architecture/data-model.md` | Every table, column, index, constraint |
| Architecture | `architecture/api-conventions.md` | REST shape, errors, pagination, concurrency, undo |
| Architecture | `architecture/auth-and-permissions.md` | Auth modes, identity linking, permission matrix |
| Architecture | `architecture/realtime-jobs-events.md` | Outbox, event catalog, WebSocket protocol, jobs |
| Architecture | `architecture/configuration.md` | Every setting, per environment |
| Architecture | `architecture/embedding-and-portability.md` | Plugging Momentum into another project; lift-and-shift |
| Frontend | `frontend/frontend-architecture.md` | Stack, folders, data layer, state, routing, patterns |
| Frontend | `frontend/design-system.md` | Tokens, typography, color rules, components, motion, a11y |
| Frontend | `frontend/ux-specs.md` | Screen-by-screen specs, keyboard map, empty/error states |
| AI | `ai/ai-architecture.md` | LLM gateway, tool registry, action safety, context and RAG, prompts, cost |
| AI | `ai/agents.md` | Agent model, runtime, every starter agent spec |
| Engineering | `engineering/coding-standards.md` | Backend and frontend conventions with templates |
| Engineering | `engineering/testing-strategy.md` | Test pyramid, fixtures, AI evals, what to test per slice |
| Process | `process/ai-dev-workflow.md` | Slice lifecycle, doc rules, handoffs, commits |
| Roadmap | `roadmap/roadmap.md` | Phases, dependencies, milestones |
| Roadmap | `roadmap/phase-0.md` … `phase-9.md` | Epics → slices with acceptance criteria and tests |
| Progress | `progress/STATUS.md` | Live tracker (updated every slice) |
| Decisions | `adr/` | Architecture Decision Records |
| Integrations | `integrations/asana-import.md` | Asana → Momentum data mapping and import algorithm |
| Runbooks | `runbooks/local-development.md` | Local setup and troubleshooting |
| Templates | `templates/` | Slice spec, ADR, phase kickoff |
