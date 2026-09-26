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
**Built (2026-09-26):** as scoped plus the approved optional rerank (off by default, `llm-check` row) and recursive subtask visibility. Migration 0017. No UI in this slice (Ask Mo and ⌘K use it).

### S3.1.5: Workspace memory + context builders
**Scope:** migration `ai_memory`; admin UI to edit memory bullets; context builders with token budgets (tiktoken-like estimate, conservative), golden snapshot tests.
**Size:** M
**Built (2026-09-26):** migration 0018; `ai/memory.py` + `/api/v1/ai/memory` (workspace/team/project scopes, undoable); `ai/context/`; `/settings/ai` page ("AI settings" in the user menu) with the workspace memory editor (read-only for non-admins). The UI edits workspace memory only; team/project bullets are API-only until a project settings screen needs them.

## E3.2 Command bar

### S3.2.1: Smart quick-add (local parse + AI fallback)
**Scope:** local parser for `@person`, `#project`, `!priority`, NL dates, "every …" (stored for P4); unparsed complex input → `fast` alias structured extraction.
**AC:** 30 fixture phrases parse correctly (local + mock AI).
**Size:** M
**Built (2026-09-26):** 24 local phrases (`quickAddParse.test.ts`) + 6 AI phrases (`test_ai_quick_add.py`, mock fixtures `quick_add.yaml`) = 30, all passing. `POST /ai/quick-add` (creates nothing; resolves names to people/projects the user can add to). The task service now writes `priority` and `recurrence` (they had no write path), which also made `priority` available to the AI tools. First versioned prompt + the structured-output helper.

### S3.2.2: ⌘K natural-language commands
**Scope:** intent detection (command vs search) in the palette; `POST /ai/command` SSE: tool loop (read tools) → proposed operations → `ai_actions` → PreviewCard in the Mo panel; "auto-apply low risk" user setting.
**AC:** J7 passes; ambiguous targets produce a clarification question instead of a guess.
**Size:** L
**Built (2026-09-26):** `ai/loop.py` (shared tool loop: reads run, writes only preview), `ai/command.py` + `POST /ai/command` (SSE: `tool_call`, `tool_result`, `token`, `action_proposed`, `action_applied`, `clarify`, `done`, `error`), `ai/sse.py`, `GET/PUT /ai/prefs` (`auto_apply_low_risk`, never high risk), prompt `command/v1`. Palette: local intent heuristic → "✦ Ask Mo to do this" first; the Ask Mo panel shows runs (activity line, reply, PreviewCard, candidate chips, errors) and takes typed commands until chat (S3.3.1) extends it; Edit → ⌘K pre-filled. Mock fixtures gained `turn` and `$last.<path>` for multi-step loops. **J7 passes** (Playwright, real API + Postgres, mock LLM). Screen context comes from the route; list selections aren't sent yet.

## E3.3 Ask Mo

### S3.3.1: Chat backend + panel
**Scope:** migrations `ai_conversations`, `ai_messages`; `POST /ai/chat` SSE (events per api-conventions §8), context chip from screen, citations, tool activity lines, write proposals as PreviewCards; panel + `/ask` page with history; feedback 👍/👎 (`feedback` table).
**AC:** J8 passes; every `[T-n]` citation links to a visible task; answers state uncertainty when retrieval is empty.
**Size:** L
**Built (2026-09-26):** migration 0019 (`ai_conversations`, `ai_messages`, `feedback`); `ai/chat.py` (`start_turn` stores the question in the request's transaction so it survives a failed answer; `run_chat` runs hybrid retrieval for the question first, so an empty result is known and the prompt tells Mo to say it couldn't find it, then the shared tool loop with **streaming** (`run_tool_loop(stream=True)`), 8 steps, 60 s); `ai/citations.py` (every `[T-n]`/`[P:Name]` resolved as the reader: only existing, visible things become links; re-resolved when history is read, since access can change); `emit_proposals` shared with ⌘K; prompt `chat/v1`; endpoints `POST /ai/chat` (SSE), `GET /ai/conversations`, `GET /ai/conversations/{id}`, `PUT /ai/feedback`. Frontend: the Ask Mo panel's input is now chat (⌘K commands still arrive there), "New chat", "Open chats page"; `/ask` and `/ask/:id` (history list + thread); citation chips; 👍/👎; shared `MoThread`/`MoComposer`. **J8 passes** (Playwright, real API + Postgres, mock LLM). Mock transport: `turn` counts from the latest user message, fixture text takes `{{$last.<path>}}`. Not built: deleting or renaming conversations; the "context chip" is the conversation's recorded context plus the screen sent with each message (S3.3.2 adds the explicit entry points).

### S3.3.2: Contextual entry points
**Scope:** "Ask about this task/project/selection" buttons pre-loading context; suggested prompts per screen.
**Size:** S
**Built (2026-09-26):** `AskMoButton` (task pane header, project header, list bulk bar; hidden while AI is off) opens Ask Mo on a **new chat pinned** to that task / project / selection: a chip ("About T-12 Draft pricing copy", × to unpin) and every message sends that as the screen (`{kind: task, task_id}`, `{kind: project, project_id}`, or the project + `selected_task_ids`; the server drops ids the user can't see). Unpinned, the screen comes from the route, now including the task open in the pane (`?task=`). An empty chat offers starter questions for the pinned context or the current screen (`features/ai/suggestions.ts`, generic wording, no seeded names). With AI off the panel says so instead of taking messages. No backend change: the chat context builders already use the screen (task → `task_ctx`, project → `project_ctx`, selection → `screen_ctx`'s selected list).

## E3.4 Inline AI actions

| Slice | Scope | AC | Size |
|---|---|---|---|
| S3.4.1 Summarize thread + inbox catch-up | `POST /ai/summarize` (task thread / inbox unread), cached by content hash, AICallout | Summary cites comments; cache hit on repeat | M |
| S3.4.2 Break into subtasks | Preview of 3–10 subtasks with optional assignees/dates → apply | Uses project members only | S |
| S3.4.3 Draft status update | Migration `status_updates`; project header "Draft status" → AICallout draft (status + summary + completed/slipped/blockers/next with keys) → edit → publish; overview shows history | Every claim references real activity (eval: citation validity 100%) | M |
| S3.4.4 Writing help | Improve / shorten / fix grammar / change tone / translate in Tiptap bubble menu | Result as suggestion with accept/reject | S |
| S3.4.5 Plan my day | Orders today's tasks considering due, priority, estimates, (calendar in P7); proposes moving items to Today/Later | Proposal applied via my_task_placements | M |
| S3.4.6 Project from brief | Paste/upload brief → plan preview (sections, tasks, relative dates, roles→members) → create project | Plan fits a requested end date; unknown people become unassigned + note | M |

**S3.4.1 built (2026-09-26):** `ai/summarize.py`, `POST /ai/summarize {target: task_thread|inbox, task_id}` (fast alias; prompts `summarize_thread/v1`, `summarize_inbox/v1`). Threads are sent as labelled comments `[C1]…[Cn]` (newest 60, the rest counted), cited labels map back to the comments (author, date; a label not in the thread is invalid), task keys resolve as the reader. Cached in `ai_summaries` by a hash of prompt version + model + the exact content (comment ids, text, edits; unread notification ids): a repeat is instant and costs nothing; a new, edited or deleted comment makes a new summary; two people get the same cached thread summary. UI: "Summarize" in the task feed (2+ comments), "Catch me up" in the inbox; results in an AI callout with citation chips; nothing to summarize → 422 with a readable message; outage → "Mo is unavailable". Mock fixtures gained `{{$keys}}` (task keys in the prompt).
**S3.4.2 built (2026-09-26):** `ai/breakdown.py`, `POST /ai/tasks/{id}/subtasks {hint?}` → `{action_id, notes, count}` (default alias, prompt `breakdown/v1`, structured `submit_result` with 3–10 items). The output is checked, not trusted: assignees only from the project's people (explicit non-viewer members, plus the team for team-visible projects; ambiguous names never guessed), dates before today or after the parent's due date dropped, duplicates of existing subtasks (or each other) skipped, each with a note. The rest is one `create_subtasks` call proposed as an AI action (`source=inline`, `source_id` = the task), so preview/apply/stale check/one undo come from S3.1.3. UI: "Break down" in the pane's Subtasks header (editors, AI on) with optional guidance, the notes, and a PreviewCard.

**S3.4.3 built (2026-09-26):** migration 0020 `status_updates`; domain `status_updates` (service, the one write path: sets the project status, undo withdraws and restores the previous status; `GET/POST /projects/{id}/status-updates`, citations resolved per reader); tool `create_status_update` (medium); `ai/status_draft.py` + `POST /ai/projects/{id}/status-draft` (default alias, prompt `status_draft/v1`): facts collected server-side, **every remaining claim cites a task from the facts** (uncited or out-of-facts claims removed with notes; stray summary keys stripped). UI: project header "Draft status" + status chip; the **Overview** tab is now live with the status history, "Post update" and "Draft with Mo" (editable AICallout, posted as the user and marked AI-drafted, undo toast). The rest of Overview stays Phase 6.

**S3.4.4 built (2026-09-26):** `ai/write.py` + `POST /ai/write {action: improve|shorten|fix_grammar|tone|translate, text ≤ 8000, tone?, language?}` → `{text}` (fast alias, prompt `write/v1`; text sent as data with line breaks kept and `<` escaped; wrapping quotes/fences removed; an empty reply is `bad_response`; language names validated). UI: a **"Mo" menu in the editor's toolbar** (not a floating bubble menu: that needs a floating-UI dependency the toolbar doesn't) on the task description: it works on the selection, or the whole text when nothing is selected, and shows the rewrite as a suggestion (Replace / Try again / Reject). Replace inserts it as Markdown, and is refused if the text changed since asking. The comment editor doesn't have it yet (it has its own small editor).

**S3.4.5 built (2026-09-26):** `ai/plan_day.py` + `POST /ai/plan-my-day` (default alias, prompt `plan_day/v1`): the model sees my open tasks (key, My Tasks section, due/overdue, priority, blocked) and submits keys for Today (ordered) and Later; the server keeps only my open tasks' keys, drops duplicates, caps Today at 8, only moves to Later what is in Today (notes for each), and proposes nothing when the day already matches. Applied through the new tool `plan_my_day` (low risk) → `mytasks.move_my_task` (the plan goes first in Today, pinned, one undo); `mytasks.first_in_bucket` added. UI: "Plan my day" on My Tasks → reasons with citations, notes, PreviewCard. No estimates field exists yet and calendar time is Phase 7, so neither is considered.

## E3.5 Quality and admin

### S3.5.1: Eval harness
**Scope:** `ai/evals` runner, scorers (structural, citation validity, schema validity, judge in live mode), fixtures for command, chat, status draft, subtasks, summarize, plan-my-day; `make evals`; report output.
**Size:** M

### S3.5.2: AI usage and settings (admin)
**Scope:** admin AI page: enable/disable, auto-apply policy, budget, usage by feature/user/day (from `llm_calls`), memory editor link, model alias display (read-only).
**Size:** S
