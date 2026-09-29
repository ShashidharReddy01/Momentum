# ADR-0009: Agent extension points (host tools, host agents, code-backed agents, API tokens)

- **Status:** Accepted (items 1–3 and 5 built in S5.1.5; item 4 built in S5.1.6)
- **Date:** 2026-09-28
- **Deciders:** product owner, AI (drafted)

## Context
The product owner will build customer-operations work (SQQ questionnaires, discovery, invoice extraction, contract drafting, data uploads to internal systems) **in their own codebase**, on top of Momentum (STATUS scope note, 2026-09-26). That work needs to:

1. add its own **AI tools** (e.g. `extract_invoice`, `draft_contract`, `push_to_erp`) and its own **agents** that use them;
2. make **Python scripts** assignable teammates: assigning a task to "Data Uploader" runs code, not a model loop, and the result lands on the task like any agent's;
3. let **scripts outside the process** call Momentum's API as a person or an agent account.

As planned before this ADR, Phase 5 agents were LLM loops defined only by Momentum's packaged YAML. The tool registry already accepts extra tools (`catalog.build_registry(*extra)`, S3.1.2). API tokens were parked in Phase 7 (S7.1) as open question #5. The `api_tokens` table exists since migration 0001, but nothing authenticates with it.

## Decision
1. **Host tools.** The app factory accepts extra tools, which are passed to `build_registry`. **As built:** one `Extensions` object carries tools, handlers and definition dirs. It is given to the app factory or named by `MOMENTUM_AGENT_EXTENSIONS`, which is how a separate worker process gets it too. They follow the same rules as built-in tools: a `risk` level, a dry-run path, services-only writes.
2. **Host agent definitions.** The agent definitions loader reads the packaged `momentum/agents/definitions/` plus any directories the host passes to the app factory. `momentum agents install` installs from all of them. A definition's `tools` may name host tools.
3. **Agent kinds.** `agents.kind` is `llm` (default: the agents.md §2 loop) or `handler`. A `handler` agent names a Python callable that the host registered with the app factory (`handlers={"erp_upload": fn}`). Its triggers, runs, trace, dedupe, timeout, kill switches, permissions (its own account, explicit project membership) and runs page are the same as an `llm` agent's.
   - Writes go through services as the agent account (`via="agent"`), so they record activity, can be undone and show the ✦ marker.
   - A handler can **propose** instead of applying (through `ai/actions.py`) when its author wants a human to confirm.
   - Model calls through the handler's `llm` handle count toward the agent's budget.
   - Autonomy doesn't apply to handler code, which is trusted code the host deployed. The agents.md §3 guards still apply in services: no deleting, no completing humans' tasks, no deciding approvals.
4. **API tokens move to Phase 5.** Personal API tokens (create with scopes and expiry, shown once, revoke) are accepted by the auth layer as an `AuthProvider` alongside Easy Auth/dev.
   - An admin can also issue a token **for an agent account**, so an external script acts as that agent (`via="api"`, actor = the agent).
   - Scopes limit what a token can do on top of normal permissions.
   - This answers open question #5: keep tokens. MCP stays dropped.
5. **Attachment text for agents.** A read tool `get_attachment_text` (permission-checked, length-capped, wrapped in `<data>`) gives extraction agents a whole document. Search only returns snippets.

## Alternatives considered
| Option | Pros | Cons |
|---|---|---|
| Build customer agents inside Momentum | One codebase | Contradicts the product owner's scope decision; couples Momentum to one business |
| Scripts only through outgoing webhooks + API (Phase 7) | No in-process code | Nothing until Phase 7; every script re-implements auth, retries, tracing; no runs page |
| Handler agents only, no tokens | Smaller | Scripts outside the process (existing Python jobs) can't participate |
| Implicit agent access via scope | Simpler setup | Rejected at kickoff (Q1): access stays explicit membership |

## Consequences
- **Positive:** the owner's codebase plugs in tools, agents, scripts and external callers without forking Momentum. Every automated actor, whether model or code, is visible, budgeted, killable and undoable in one place.
- **Negative:** tokens are a new way to authenticate, and that needs its own security tests (hashing, scopes, revocation, expiry, never logged). Handler code runs in the worker, so a bad handler can hurt the worker; the timeout and per-run isolation (its own transaction) limit that.
- **Follow-ups:** INTEGRATION_GUIDE gets an "Extending agents" section and a change-log entry. `data-model.md` gains `agents.kind`/`handler`. S7.1 in `phase-7.md` points here. Deferred: customer-onboarding workflow features (conditional template items, template versions applied to running projects, agent pre-fill of forms, document generation). The product owner will build these later.
- **Reversal:** `kind` defaults to `llm`, and an unregistered handler makes the agent refuse to run with a clear error. Host extras are optional arguments, so removing them leaves stock Momentum.
