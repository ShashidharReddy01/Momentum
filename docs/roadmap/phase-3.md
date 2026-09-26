# Phase 3: AI Layer v1 ("Mo")

**Goal:** Mo works everywhere: ⌘K natural language with preview/apply/undo, Ask Mo chat with citations, inline AI actions, status drafts, plan my day, project from a brief, and semantic search. Milestone **M3**.

**Read first:** ai/ai-architecture.md (all), engineering/testing-strategy.md §6.

**Kickoff prerequisite:** confirm the gateway model aliases (fast/default/smart) and the Cohere v3 variant (English vs. multilingual) for local testing, or run in mock mode plus a personal gateway. **Resolved at kickoff (2026-09-26):** built in mock mode; the product owner's gateway is Portkey (OpenAI-compatible), Cohere English. See `phase-3-kickoff.md` for the state check and refinements.

**Exit criteria:** J7, J8 pass (mock); `EVALS_LIVE=1 make evals` passes the thresholds against a real LiteLLM; the AI-unavailable path degrades gracefully; the usage page shows accurate token counts.

---

## E3.1 Platform

### S3.1.1: LLM gateway + `llm-check`
**Scope:** `ai/llm.py` (complete/stream/embed, alias resolution, retries, error mapping, budget check, `llm_calls` logging, price table), mock and record modes, `momentum llm-check` (verifies: basic chat, tool calling with a sample tool, streaming, streaming with tool calls, embeddings with `input_type` for both types and the expected dimension, latency). Migration `llm_calls`.
**AC:** `llm-check` prints a pass/fail table and recommends `LLM_SUPPORTS_STREAMING_TOOLS` if streaming tool calls fail.
**Size:** M
**Built (2026-09-26):** as scoped, plus configurable key header / extra headers for Portkey-style gateways and `prompt_version` on `llm_calls` (see kickoff §3). Migration 0015.

### S3.1.2: Tool registry + sweep of existing services
**Scope:** `@tool` decorator, schema export, `TaskRef` resolution, dry-run via SAVEPOINT with diff capture, `ToolResult`. Register all Phase 1–2 tools from the catalog (ai-architecture §3). Snapshot tests of JSON schemas.
**AC:** every write tool has a dry-run test producing a correct diff, and permission is enforced when called with a principal lacking rights.
**Size:** L
**Built (2026-09-26):** `momentum/ai/tools/` (`base`, `refs`, `schema`, `registry`, `views`, `read_tools`, `write_tools`, `catalog`). 8 read + 9 write tools: every catalog tool whose services exist after Phase 2. `semantic_search` moves to S3.1.4 and `create_status_update` to S3.4.3 (their tables don't exist yet). Tools live in `momentum/ai/tools/`, not in a `tools.py` per domain module, so the domain never imports AI (coding-standards §2 updated). No migration, no endpoint, no domain change. Priority isn't settable because no service writes it yet. `llm-check` gained a `tool schemas (catalog)` row: all tool schemas in one request, with `update_task` forced and its arguments validated.

### S3.1.3: AI actions (preview → apply → undo)
**Scope:** migration `ai_actions`; `ai/actions.py` lifecycle incl. stale check, expiry job, batch apply, undo; API `GET /ai/actions/{id}`, `POST /ai/actions/{id}/apply|reject`; frontend `PreviewCard` (diff rows grouped by entity, risk indicator, Apply/Edit/Cancel, high-risk confirm dialog), undo toast.
**AC:** applying a 30-item bulk requires high-risk confirmation; stale targets trigger re-preview.
**Size:** L
**Built (2026-09-26):** as scoped; migration 0016; also `POST /ai/actions/{id}/undo` (so an undone action's state is `undone`, not just its batch) and a `/ai/actions/:id` page. `Edit` is a host callback (wired by ⌘K in S3.2.2). No source creates actions yet from the UI: ⌘K (S3.2.2) and chat (S3.3.1) do.

### S3.1.4: Embeddings pipeline + hybrid retrieval
**Scope:** migration `embeddings` (vector(1024) + HNSW), `ai_summaries`; `ai/embeddings.py` (chunking, `input_type`, batching, content hash); consumer job on create/update events; `momentum reindex [--entity] [--since]`; `ai/retrieval.py` hybrid search with RRF + SQL permission filter; `semantic_search` tool.
**AC:** search for a paraphrase finds the right task (fixture); private content never returned to non-members (test).
**Size:** L

### S3.1.5: Workspace memory + context builders
**Scope:** migration `ai_memory`; admin UI to edit memory bullets; context builders with token budgets (tiktoken-like estimate, conservative), golden snapshot tests.
**Size:** M

## E3.2 Command bar

### S3.2.1: Smart quick-add (local parse + AI fallback)
**Scope:** local parser for `@person`, `#project`, `!priority`, NL dates, "every …" (stored for P4); unparsed complex input → `fast` alias structured extraction.
**AC:** 30 fixture phrases parse correctly (local + mock AI).
**Size:** M

### S3.2.2: ⌘K natural-language commands
**Scope:** intent detection (command vs search) in the palette; `POST /ai/command` SSE: tool loop (read tools) → proposed operations → `ai_actions` → PreviewCard in the Mo panel; "auto-apply low risk" user setting.
**AC:** J7 passes; ambiguous targets produce a clarification question instead of a guess.
**Size:** L

## E3.3 Ask Mo

### S3.3.1: Chat backend + panel
**Scope:** migrations `ai_conversations`, `ai_messages`; `POST /ai/chat` SSE (events per api-conventions §8), context chip from screen, citations, tool activity lines, write proposals as PreviewCards; panel + `/ask` page with history; feedback 👍/👎 (`feedback` table).
**AC:** J8 passes; every `[T-n]` citation links to a visible task; answers state uncertainty when retrieval is empty.
**Size:** L

### S3.3.2: Contextual entry points
**Scope:** "Ask about this task/project/selection" buttons pre-loading context; suggested prompts per screen.
**Size:** S

## E3.4 Inline AI actions

| Slice | Scope | AC | Size |
|---|---|---|---|
| S3.4.1 Summarize thread + inbox catch-up | `POST /ai/summarize` (task thread / inbox unread), cached by content hash, AICallout | Summary cites comments; cache hit on repeat | M |
| S3.4.2 Break into subtasks | Preview of 3–10 subtasks with optional assignees/dates → apply | Uses project members only | S |
| S3.4.3 Draft status update | Migration `status_updates`; project header "Draft status" → AICallout draft (status + summary + completed/slipped/blockers/next with keys) → edit → publish; overview shows history | Every claim references real activity (eval: citation validity 100%) | M |
| S3.4.4 Writing help | Improve / shorten / fix grammar / change tone / translate in Tiptap bubble menu | Result as suggestion with accept/reject | S |
| S3.4.5 Plan my day | Orders today's tasks considering due, priority, estimates, (calendar in P7); proposes moving items to Today/Later | Proposal applied via my_task_placements | M |
| S3.4.6 Project from brief | Paste/upload brief → plan preview (sections, tasks, relative dates, roles→members) → create project | Plan fits a requested end date; unknown people become unassigned + note | M |

## E3.5 Quality and admin

### S3.5.1: Eval harness
**Scope:** `ai/evals` runner, scorers (structural, citation validity, schema validity, judge in live mode), fixtures for command, chat, status draft, subtasks, summarize, plan-my-day; `make evals`; report output.
**Size:** M

### S3.5.2: AI usage and settings (admin)
**Scope:** admin AI page: enable/disable, auto-apply policy, budget, usage by feature/user/day (from `llm_calls`), memory editor link, model alias display (read-only).
**Size:** S
