# Phase 3 Kickoff

**Date:** 2026-09-26 · **Model:** Opus 5.5 (whole phase, per `docs/process/model-guide.md` §2) · **Phase goal:** Mo works everywhere: ⌘K natural language with preview/apply/undo, Ask Mo chat with citations, inline AI actions, status drafts, plan my day, project from a brief, semantic search (M3).

## 1. Kickoff prerequisite: gateway and aliases

The phase file asks for the model aliases and the Cohere variant to be confirmed, **or** for the phase to run in mock mode.

- **This build environment has no LLM access**, so Phase 3 is built and tested in **mock mode** (`MOMENTUM_LLM_MODE=mock`). The gateway's real code path is still covered: tests run the real OpenAI SDK against an in-process fake OpenAI-compatible server.
- **What the product owner uses (2026-09-26):** **Portkey**, not LiteLLM. It is OpenAI-compatible, takes its key in an `x-portkey-api-key` header, and addresses Bedrock models as `@<provider-config>/<model id>`. It serves Claude Sonnet (chat), Cohere `embed-english-v3` (1024 dimensions, which matches `vector(1024)`), and Cohere `rerank-v3.5`. S3.1.1 therefore adds `MOMENTUM_LLM_API_KEY_HEADER` and `MOMENTUM_LLM_EXTRA_HEADERS`, so Portkey vs. LiteLLM is a configuration difference only (ADR-0004 amendment).
- **Still open (Open question #1, narrowed):** which model ids to use for the `fast` and `smart` aliases. Until they're decided, both can point at the same Sonnet id; `llm-check` pings each alias separately.
- **Cohere variant:** English (`embed-english-v3`), as used in the product owner's own pipeline.
- **Exit criterion `EVALS_LIVE=1 make evals` against a real gateway:** only the product owner can run it (their key). Plan: they run `momentum llm-check` as soon as S3.1.1 lands, and the live evals at phase exit.

## 2. State check (code vs. phase file)

| Area | Reality after Phase 2 | Consequence |
|---|---|---|
| `momentum/ai`, `momentum/agents` | Empty packages | S3.1.1 creates the gateway. Layout follows ai-architecture §1. |
| Settings | AI settings partly present (mode, URL, key, aliases, embed dim); budget/retry/timeout/price settings documented but not in `Settings` | Added in S3.1.1, plus the key-header and extra-headers settings for Portkey |
| Dry-run | `Ctx.dry_run` and `UnitOfWork(dry_run=True)` exist (rollback instead of commit); `core/events.py` already skips outbox writes on dry runs | S3.1.2 builds the SAVEPOINT + diff capture on top of it rather than inventing a second mechanism |
| Undo | `POST /undo` takes `activity_id` **or** `batch_id` (Phase 1) | AI action undo (S3.1.3) reuses batch undo; no new undo executor |
| Permission filters | `domain/access.py` has `visible_projects_clause` and `get_visible_task`. ai-architecture §5 names a `visible_tasks_clause` that **doesn't exist** | Retrieval (S3.1.4) and context builders (S3.1.5) use the same project-membership clause every Phase 2 bulk endpoint and search already use. A true per-task SQL clause (follower/assignee-only access) needs human approval (CLAUDE.md §6: `access.py` is permission semantics), so the gap is disclosed per slice, not silently widened |
| Keyword search | `search_tsv` + trigram indexes on tasks, projects, comments (S2.6.2) | Hybrid retrieval's keyword half exists; S3.1.4 adds the vector half + RRF |
| Background jobs | Procrastinate; the S2.6.1 attachment-extraction job is the precedent for a DB-touching job. Outbox + `consumer_offsets` (S2.1.1) | The embedding consumer (S3.1.4) is an outbox consumer with its own `consumer_offsets` key |
| Frontend | ⌘J opens an "Ask Mo" panel placeholder; `/ask` is a placeholder route; ⌘K palette has live search (S2.6.2) | S3.2.2 and S3.3.1 fill these in. No frontend work in S3.1.1 |
| YAML | Mock fixtures, prompt front matter and eval cases are YAML; `pyyaml` was only a transitive dependency | Made explicit in S3.1.1 |

**Lessons from the Phase 2 retro that apply here:**
- E2E journeys sharing seeded users leak state across files (remembered views). J7/J8 create journey-scoped data rather than reusing seed fixtures.
- Fixtures need at least two of whatever the code chooses between (Phase 1 rule). For AI that means two candidate tasks for every "resolve a reference" case, so ambiguity handling is actually exercised.
- A fresh build container needs Postgres + pgvector set up before any backend test can be trusted (see STATUS handoff notes).

## 3. Refinements

| Slice | Change | Reason |
|---|---|---|
| S3.1.1 | `llm_calls` gains `prompt_version` (ai-architecture §7 says the prompt version is recorded there; the data model omitted it). `agent_run_id` has no FK until `agent_runs` exists (Phase 5). `llm_calls` rows are written in their own transaction | Usage of a rolled-back request (a failed apply, a dry-run preview) was still spent and must count |
| S3.1.1 | `momentum llm-check` also flags an embedding dimension mismatch and a gateway that drops `input_type` (query and document vectors identical) | Both fail silently otherwise: bad recall with no error |
| S3.1.1 | Settings validation: production refuses `LLM_MODE` ≠ `gateway` while AI is enabled | CLAUDE.md: never a silent fallback to mock output in production |
| S3.1.4 | **Approved 2026-09-26:** an optional rerank step after RRF (top 40 → Cohere rerank → k=8) behind a `rerank` alias, off by default, verified by `llm-check`. The product owner's gateway already serves `rerank-v3.5` | Better retrieval precision for Ask Mo citations; it adds a model dependency, so it's asked, not assumed (Open question #4) |

## 4. Risks

| Risk | Mitigation |
|---|---|
| Mock mode hides real-model behavior (tool-call formats, streaming quirks) | The gateway path is tested against a fake OpenAI-compatible server; `llm-check` on the product owner's gateway after S3.1.1; record mode turns real responses into fixtures |
| Gateway differences (Portkey vs. LiteLLM: auth header, `stream_options`, `input_type` passthrough, streaming tool calls) | All of these are `llm-check` rows; `MOMENTUM_LLM_SUPPORTS_STREAMING_TOOLS=false` fallback |
| Prompt injection through task/comment content | ai-architecture §8: `<data>` wrapping, tools enforce permissions, the model is never the security boundary; eval cases include injection attempts |
| Permission leaks through retrieval | SQL-side filter before ranking output; tests that private content never reaches non-members (S3.1.4 AC) |
| Cost runaway | Budget check before every call; `llm_calls` on every call; max tool-loop steps |

## 5. Questions for the human
- **Q1 (Open question #1, narrowed):** model ids for `fast` and `smart`. Recommendation: `smart` = the strongest Claude on your Bedrock config; `fast` = a Haiku-class model if your config has one, else Sonnet for both until cost says otherwise. Not blocking: mock mode until then. **Answered 2026-09-26:** keep the same Bedrock Sonnet 4 id for all three aliases for now (revisit when usage/cost data exists; S3.5.2's usage page will show it).
- **Q2 (Open question #4):** add the optional rerank step to S3.1.4? Recommendation: yes, off by default, turned on once `llm-check` shows it works on your gateway. **Answered 2026-09-26: yes**, optional Cohere rerank in S3.1.4, off by default.
- **Q3:** run `uv run momentum llm-check` against your Portkey setup once S3.1.1 is pushed and paste the table back. **Answered 2026-09-26: 8/8 pass on Portkey** (see STATUS); a slow first streaming run (13 s) was a one-off; the re-run streamed in 1.5 s.

## 6. Exit criteria (confirmed)
As in `phase-3.md`: J7, J8 pass (mock); `EVALS_LIVE=1 make evals` passes the thresholds against a real gateway (product owner runs it); the AI-unavailable path degrades gracefully; the usage page shows accurate token counts.
