# Phase 7.6: The agent platform, and Bernie the invoice agent

> **Added 2026-10-06 by the product owner**, after Phase 7.5 and before Phase 8 (Azure go-live).
> **The spec:** `docs/superpowers/specs/2026-10-06-phase-7-6-agent-platform-bernie-design.md`. Section numbers below like "spec §4.2" point into it. Read the spec fully before the first slice.
> **The code Bernie ports:** `docs/reference/coap-invoice-pipeline/` (read its README).

**Goal:** Momentum can host many agents (50–100+) as **packs**. A pack is one folder with a manifest, code, prompts, record types, settings, skills, evals and tests. Packs:
- run **durable jobs** that pause, ask people questions and resume;
- produce typed, reviewable **records**;
- learn **skills** that people approve;
- work together through **plans** that Mo drafts and a person confirms.

**Bernie, the invoice agent,** is the first and only shipped pack. He is a much stronger, agentic version of the product owner's invoice pipeline.

**How this phase is built:**
- **Prerequisite:** Phase 7.5 is complete: STATUS says so and its exit table is filled in. 7.6 builds on 7.5's `momentum.files` (parsing, page rendering), vision through the gateway, the reports engine and dashboards v2.
- **Where:** a separate browser session (Claude Code on the web). **There is no AI gateway there.**
  - Everything runs with `MOMENTUM_LLM_MODE=mock`.
  - Every AI entry point has handwritten mock fixtures and mock eval cases at threshold 1.0.
  - e2e runs on mock AI.
  - Live-only cases are written now. The product owner runs them after pulling (§ Live verification).
- **The build session can't see the product owner's other folders.** Everything it needs from the old invoice pipeline is in `docs/reference/coap-invoice-pipeline/`. Real invoices never enter the repo; tests use the synthetic generator (spec §14.1).
- **Decisions are made:**
  - The spec's D1–D12 and every choice written here are final. **Don't stop to ask.**
  - When something isn't covered, decide by the spec's principles (one write path; declared effects; asks over guesses; numbers from code; data honesty; visibility first; preview → confirm → apply → undo for anything undeclared). Record the call in STATUS under "Decisions (Phase 7.6, delegated)" and in the slice's as-built note.

**Exit criteria:**
- Every slice below done with its tests. `make check` green (it now includes `packs/`).
- e2e: J1–J24 green twice in a row (J20–J24 new).
- Mock evals: every new feature at 1.0. Live-only cases written for each.
- The UI audit (`tools/ux/audit.mjs`, with `seed --invoices`) and the keyboard pass (`tools/ux/keyboard.mjs`) both report 0 findings.
- `momentum packs new demo` → `momentum packs check demo` → its tests pass (CI test on the template).
- Performance, measured on mock and written in the as-built note:
  - a 100-invoice zip finishes in mock mode with concurrency 4 within 10 minutes on the build machine;
  - the record query p95 is < 300 ms on 50,000 invoice records (scale seed).
- Docs updated per CLAUDE.md §5:
  - data model;
  - events;
  - settings;
  - AI tools and prompts;
  - design system;
  - ADR-0012 and ADR-0013;
  - `docs/agents/*`;
  - the INTEGRATION_GUIDE change log.
- The live verification list is written for the product owner.

---

## Working rules for the build session

1. **Start of every session** (CLAUDE.md §1):
   - read `docs/progress/STATUS.md`, this file, then the spec;
   - **if Phase 7.5 isn't complete in STATUS, stop and report that** (don't build 7.6 on a half-built 7.5);
   - run the gate on the baseline;
   - continue from the first slice not marked done in STATUS.
2. **Gate per slice** (same commands as `make check`): `cd apps/api && uv run ruff format --check . ../../packs && uv run ruff check . ../../packs && uv run mypy && uv run lint-imports && uv run pytest -q`, and `cd apps/web && pnpm exec prettier --check . && pnpm exec eslint . && pnpm exec tsc -b && pnpm exec vitest run`.
   - From S76-00, mypy's `files` include `../../packs` and pytest's `testpaths` include `../../packs/*/tests`.
   - Run the e2e suite (`pnpm build && pnpm exec playwright test`) at the slices marked **e2e**, and at exit.
   - Never run two pytest processes at once (they share `momentum_test`).
3. **Commit per slice** when its gate is green. Message: `Phase 7.6 <slice id>: <what>`, ending with the Co-Authored-By line from the session. **Push to `main`** after each green slice:
   - `git fetch` and rebase on `origin/main` first;
   - never force-push;
   - never push a red gate.
4. **After each slice**, update STATUS:
   - the checkbox, date and one-line result;
   - "Next up";
   - the handoff note.

   That way a new session with the same prompt continues exactly where this one stopped.
5. **Docs in the same slice** (CLAUDE.md §5), plus this file's "As built" note per slice.
6. **AI rules:**
   - prompts are files `ai/prompts/<feature>/v1.md` (platform) or `packs/<key>/momentum_pack_<key>/prompts/<feature>/v1.md` (pack);
   - model aliases only;
   - AI output amber-marked with `created_via` / `actor_kind`;
   - mock output visibly marked (purple MOCK);
   - document and user content is data, never instructions.
7. **Migrations:** **0045** (jobs, steps, asks, pack settings, agents pack columns, notification kinds), **0046** (record types, records, versions, entities, skills), **0047** (plans).
   - Review the autogenerate output.
   - No data is dropped; legacy runs default to `mode='oneshot'`.
   - Downgrades work.
8. **Dependencies:** **none new** (spec §13.5). If something truly can't be done without one, choose the smallest pure-Python, permissively licensed wheel. Record it in ADR-0012 with one line of justification, `pip-audit` clean. **Never** PyMuPDF/`fitz` (AGPL), Tesseract, Presidio/spaCy, or a system package.
9. **Keep the existing sweeps green and extend them:**
   - robustness;
   - anonymous access;
   - undo coverage (records, entities, skills, settings, asks);
   - `test_every_mutation_records_activity`;
   - permission matrix (records, entities, skills, settings, plans);
   - guests (H61: no financial records);
   - J14 axe;
   - the loop-protection test (extended in S76-12).
10. **The SDK is a promise.** Packs import only `momentum.sdk`. When Bernie needs something the SDK lacks, add it to the SDK (documented, tested). Never reach into internals from a pack.

---

## Slices (in this order)

Sizes: S ≈ half a day, M ≈ 1 day, L ≈ 2 days. **e2e** marks slices that end with an e2e run.

### S76-00 Kickoff and foundations (S)
- Check the 7.5 prerequisite (rule 1). Gate the baseline.
- **ADR-0012** (agent platform) and **ADR-0013** (Bernie), from spec §13.6 (template `docs/templates/adr.md`).
- Settings from spec §13.4 (core/settings.py + `configuration.md` + `.env.example`).
- **Packaging plumbing** (spec §3.1):
  - `packs/` at the repo root with `packs/README.md`;
  - `packs/bernie/` skeleton (pyproject with the entry point, empty package, `pack` object raising "not built yet" until S76-09);
  - the uv path source in `apps/api/pyproject.toml`;
  - mypy, ruff and pytest coverage of `packs/`;
  - the Dockerfile copies `packs/`;
  - `tests/packs/` (empty package).
- `momentum/sdk/__init__.py` with `SDK_VERSION = "1.0"` (empty facade).
- **Import contracts:**
  - `momentum_pack_bernie` may import only `momentum.sdk` from Momentum;
  - `momentum.sdk` is the facade;
  - the domain modules added later follow the domain contract.

  Prove each contract with a deliberate bad import that fails `lint-imports`, then remove it.
- STATUS: Phase 7.6 in progress; the "Plan changes" row.
- **AC:**
  - gate green;
  - ADRs merged;
  - `uv sync` installs the Bernie package editable;
  - `python -c "import momentum_pack_bernie"` works in the API venv;
  - the contracts are enforced.

### S76-01 Packs: manifest, loader, install, setup (M)
- `momentum/agents/packs/`:
  - `manifest.py` (`PackManifest`, spec §3.2, `extra="forbid"`);
  - `loader.py` (entry points `momentum.packs`, `MOMENTUM_PACKS` filter, SDK range check, `MOMENTUM_TEST_PACKS` loading `tests/packs/`);
  - `registry.py` (packs by key, capabilities by key).
- `momentum.sdk`: `Pack`, `Capability`, `PackSettings` base.
- **Migration 0045, part 1:** `agents.pack_key`, `agents.pack_version`, `kind` value `pack`.
- **Install / upgrade / drift** extended to packs (spec §3.3); the display fields come from the manifest; effects, capabilities and data are always read from code.
- **Setup checklist** infra (spec §3.4): the pack's `setup` returns a preview of declared changes; confirmed by the admin when adding the agent to a project; applied as one undoable batch.
- `momentum packs list`, `momentum packs check` (manifest validation, contract present; more checks added as features land).
- First test pack: `tests/packs/echo`.
- **Tests:** `test_packs_loader.py`.
- **AC:** an echo pack installs disabled, appears in `GET /agents`, survives upgrade rules, and its setup preview applies and undoes.

### S76-02 Durable jobs (L)
- **Migration 0045, part 2:** the `agent_runs` columns (spec §4.1) and `agent_run_steps`.
- `momentum/agents/jobs/`:
  - the engine (claim → run → `Suspend` → waiting → resume);
  - replay (`job.step`, `job.now`, `job.uuid`; output (de)serialisation by return annotation; large outputs to storage);
  - effects only inside steps;
  - `spawn` / `gather` (children, concurrency, the parent doesn't hold the task slot);
  - `sleep_until`, `wait_for_event` (outbox consumer wakes waiting jobs);
  - step timeouts, `active_seconds`, max age → `expired`;
  - per-job budget across children;
  - transient retries with backoff;
  - retry from the failed step, cancel, pause, resume;
  - agent off → pause;
  - **undo everything** (`request_id` on activity, spec §4.7).
- Events `agent_run.waiting/resumed/progress/step`; the realtime channel `run:<id>`.
- **SDK:** `Job` with the above, plus `job.llm.complete/json/vision` as recorded `llm` steps (the JSON helper tolerates fences and preambles and retries empties, as in `llm_json.py`), `job.prompts.load`, `job.log`, `job.progress`.
- Legacy runs untouched (`mode='oneshot'`).
- **Determinism lint** (`test_pack_determinism.py`).
- Test packs `failer` and `spawner`.
- **Tests:** `test_jobs_replay.py`, `test_jobs_waiting.py`, `test_jobs_budget.py`, `test_jobs_undo_all.py`.
- **AC:**
  - a job killed between steps (simulated) resumes without re-running finished steps or duplicating effects;
  - a parent with 20 children runs 4 at a time and finishes;
  - every Phase 5 agent test still passes.

### S76-03 Asks and conversation (L)
- **Migration 0045, part 3:** `asks` and the notification kinds `agent_ask`, `agent_ask_reminder`, `skill_proposed`.
- `domain/asks/` (service, router):
  - create through the SDK only;
  - answer (validation per kind);
  - cancel, expire, remind (a periodic job `ask_timers`, every 5 minutes, maintenance queue);
  - undo an answer before the job consumed it.
- Routes and fallbacks (spec §5.4); who may answer (never guests).
- **Ask cards:** the comment rendering contract (an `ask` node in the comment doc, so the existing thread shows it). The web lands in S76-07; build the API and the doc node here.
- **Thread replies:** `POST /asks/{id}/interpret`. `interpret_reply` (prompt `ask_interpret/v1`, `fast`, mock fixtures): certain → apply; ambiguous → confirm.
- **Conversation runs** (spec §5.6): `converse` capability plumbing; manifest `commands`; `job.wait_for_instruction`; the confirm ask before any command acts.
- `GET /asks?mine=open`; Mo read tool `list_my_asks`.
- Test pack `asker`.
- **Tests:** `test_asks.py`.
- **Evals:** `ask_interpret` (≥ 10 mock).
- **AC:** every ask kind round-trips; expiry defaults behave; a thread reply answers when certain and asks to confirm when not; guests can't answer.

### S76-04 Records (L)
- **Migration 0046, part 1:** `record_types`, `records`, `record_versions` (spec §6.2).
- `domain/records/`:
  - type registry sync at install;
  - create / update with **correction operations** (spec §6.4, `distribute` with Decimal remainder);
  - the `recheck` hook;
  - versions and undo; `expected_version` → 409;
  - identity normalisation and the duplicates / similar helpers;
  - visibility (spec §6.7, guests never see financial or personal);
  - the **query engine** (`RecordQuery`, per-currency sums, array unnest, caps);
  - pages endpoint (7.5 render, cached).
- **SDK:** `RecordModel`, `RecordType`, `Money` (Decimal, string JSON), `job.effects.create_record/update_record`, `job.records.*`.
- **Reports:** kind `records_export` (xlsx header + lines sheets, csv).
- **Dashboards v2:** QuerySpec entities `records` and `record_lines`; the role template **"Accounts payable"** (spec §6.6), with widgets that degrade to empty states when there are no records.
- **Mo tools:** `search_records`, `get_record`, `query_records` (read, visibility-filtered; numbers from the server).
- The echo pack gets a test record type.
- **Tests:** `test_records.py`, the dashboard tests extended, export tests.
- **Evals:** `records_qa` (≥ 10 mock: Mo answers spend questions with numbers equal to the server's).
- **AC:** a record can't be saved invalid; money never mixes currencies; a guest sees no financial record by any route (API, search, Mo, dashboards, export).

### S76-05 Entities, skills, pack settings (L)
- **Migration 0046, part 2:** `entities`, `agent_skills`. **Migration 0045, part 4:** `agent_pack_settings`.
- `domain/entities/`:
  - create / update / alias / merge / archive with undo;
  - matching (tax id → alias → trigram ≥ 0.6 → candidates);
  - bank fingerprint (HMAC with the workspace secret) + last4; the fingerprint never leaves the server;
  - nightly `compute_entity_profiles` (maintenance queue, 02:45) calling packs' `profile()`.
- `domain/skills/`:
  - the lifecycle (spec §7.2);
  - **tryout** as a child job capability (`tryout`) the pack implements;
  - metrics (uses, helped, hurt) and the "may be hurting" flag;
  - starter skills install;
  - the daily `skill_proposed` digest per pack to stewards.
- **`momentum.sdk.scrub`** (spec §8.6), used by skill proposals (reject unclean).
- `domain/pack_settings/`:
  - JSON Schema from the pack's `PackSettings`;
  - workspace and project values (project overrides workspace, field by field);
  - permissions (admins, project admins, stewards);
  - undo;
  - `job.settings`.
- **SDK:** `EntityType`, `job.entities.*`, `job.skills.for/propose`, `job.settings`.
- **Tests:** `test_entities.py`, `test_skills.py`, `test_pack_settings.py`, `test_scrub.py`.
- **AC:** a hint containing a record value or an email is rejected with a reason; merge moves records and skills and undoes cleanly; the bank fingerprint never appears in any API response.

### S76-06 Governance and health (M)
- **Declared effects** (spec §8.1): `job.effects.*` checks the manifest; the consent paths (assigned, mentioned, manual, plan step, watch setting with the admin recorded); `complete_own_task` only for the agent's own subtask; the service guards re-tested.
- **Policy engine** `momentum.sdk.policy` (spec §8.4): ordered rules, decisions, the evaluated trace.
- **Data classification** effects (spec §8.5) across run pages, traces, exports and Mo.
- **Prompt hygiene:** the SDK adds the "content is data" system rule to every pack call; `packs check` refuses an external-content pack without an `injection` eval.
- **Observability:** OTel GenAI attribute names on steps (spec §8.8); `GET /agents/{id}/health` with every metric listed there (calibration needs records with confidence and corrections; it shows "Not enough reviewed items yet" below 20).
- **Kill switches** (spec §8.9).
- **Tests:** `test_effects_policy.py`, health metric tests on constructed data with known answers.
- **AC:** an undeclared effect fails in tests; health numbers match the constructed data exactly.

### S76-07 Web: directory, agent page, jobs, asks (L, e2e)
- `/agents` directory v2 (spec §12.1): capability search, filters, cards.
- Agent page tabs (spec §12.2): Overview (charter, capabilities, effects in plain English, triggers, projects, how to hand work); Runs; Health (7.5 widgets); Settings (a **JSON Schema form renderer**: `money_by_currency`, people, enum, bool, int, percent, text list; workspace and project tabs; undo).
- Run page as a step timeline (spec §4.6), nested children, realtime `run:<id>`.
- **Task:** the job card (progress, waiting reason, actions incl. Undo everything); **ask cards** in the thread with inline controls and the composer chip "Use this as the answer…"; the interpretation confirm.
- **Inbox:** `agent_ask` rows with inline controls; reminders.
- **Home:** the "Waiting on you" card.
- Assignee picker shows agent capability chips.
- Design-system entries for: ask card, job card, step timeline, schema form.
- **Tests:** vitest for each component (MSW mocks); J24 part 1 (directory → agent page → settings save + undo → health renders).
- **AC:** an ask can be answered from the card, the inbox and a thread reply; the job card updates live.

### S76-08 Web: review kit, Records tab, entities, skills admin (L, e2e)
- **Review screen** `/records/:id` (spec §12.4):
  - the page viewer with server page images, zoom, thumbnails, provenance boxes (SVG overlay) both ways (field ↔ box);
  - a record form generated from the type's JSON Schema and display spec;
  - array grid (keyboard, add / remove / reorder, totals row);
  - checks; decision panel; entity panel; version history with diffs;
  - save as ops, conflict handling, approve / reject when allowed.
- **Project tab "Records"** (spec §12.5): type switcher, table, filters, totals per currency, export, bulk actions.
- **Entities** list and page.
- **Skills admin** (spec §12.6): proposed queue with tryout before/after, active list with metrics and the hurting flag, history.
- The record panel on tasks.
- Design-system entries: page viewer with highlights, record form, array grid.
- **Tests:** vitest; J14 pages added (review screen, Records tab, skills admin) for axe and keyboard.
- **AC:** every review action is keyboard-reachable; a highlight has a text equivalent; totals show per currency and never mix.

### S76-09 Bernie 1: ingest and reading (L)
- **Synthetic invoice generator** (spec §14.1) with ground-truth YAML, including the Factur-X embed (pypdf `add_attachment` on a reportlab PDF/A-3-like file, enough for the parser) and the scanned page (a rendered image placed as the only page content).
- Pack modules: `records.py` (`InvoiceV1`, `INVOICE`), `entities.py` (vendor), `settings.py` (`BernieSettings`, spec §9.7), `manifest.yaml` (spec §3.2).
- **Pipeline steps 1–10** (spec §9.3): `gather`, `ingest` (port `pdf_utils`: boundaries, PAGE N OF M guard, sha256, zip limits, folder hints; **pypdf for splitting**), `.eml`/`.msg` attachments, batch children with subtasks, `duplicate_file`, `einvoice` (Factur-X, ZUGFeRD, XRechnung, UBL, CII → InvoiceV1; mismatch warning), `read` (7.5 parse, words, per-page confidence), `vendor` (hint → tax id → trigram → `bernie_vendor/v1` closed list → new or ask), `skills`, `extract` (text, chunked, vision, mixed; prompts ported from `extract.py` as `bernie_extract/v1`, `bernie_extract_chunk/v1`), `locate` (bbox provenance).
- **Mock fixtures** for every extraction call in the synth set (the fixture is the ground truth, or a deliberately wrong extraction for the S76-10 cases).
- **Setup checklist** (spec §3.4): fields, Review section, settings row.
- **Tests:** `test_ingest.py`, `test_einvoice.py`, `test_vendor.py`, `test_extract_paths.py`, `test_locate.py`.
- **Evals:** `bernie_extract`, `bernie_paths`, `bernie_vendor` (≥ 10 mock each; ≥ 5 live-only each, on the synth PDFs).
- **AC:**
  - the 300-line Tailspin invoice yields 300 lines (chunked);
  - the 3-invoice Acme PDF splits into 3, and the `Page 2 of 3` one doesn't split;
  - the Factur-X invoice makes **no model call**.

### S76-10 Bernie 2: checking, asking, deciding, outputs (L)
- **Steps 11–19** (spec §9.3):
  - `checks_math` (port `reconcile.py` with its tests, Decimal, tolerances from settings);
  - `investigate` (critic `bernie_critic/v1` ported from `self_check.py`, then the investigator tool loop `bernie_investigate/v1` with the document-only tools in spec §9.3.12, `smart`, budget-capped; **values never seen by a tool are rejected in code**);
  - `ask_gap` (form ask with crops, the four options);
  - `checks_risk` (every row of the table in spec §9.3.14);
  - `confidence`;
  - `record`;
  - `policy` (the Bernie `Policy`, tiers, holds);
  - `outputs` (fields, rename, approval subtask, hold ask, review move, comment);
  - batch summary and **catalogue** (`records_export` xlsx + the notebook's csv column order);
  - `await_decision` (`approval.decided` → record status).
- **Tests:** `test_checks_math.py`, `test_investigate.py`, `test_ask_gap.py`, `test_checks_risk.py`, `test_policy.py`, `test_outputs.py`, `test_bernie_e2e_service.py`.
- **Evals:** `bernie_investigate`, `bernie_asks`, `bernie_risk`, `bernie_policy`, `bernie_injection` (≥ 10 mock each).
- **AC:**
  - auto-approve is off by default;
  - a bank change always holds for stewards;
  - `INV-0041` vs `INV41` is caught as a duplicate;
  - a document with a hostile footer changes nothing and is flagged `instruction_text_found`.

### S76-11 Bernie 3: learning, conversation, profiles, Mo (M)
- `learn` (prompt `bernie_hint/v1` ported from `skills.py`; scrubbed; `generalizes:false` → none) and **tryout** (re-extract with vs without the skill on the source document and up to 5 vendor records; before/after).
- `profile()` (vendor stats).
- `converse` (`bernie_converse/v1`: commands rerun / explain / split / skip / status, questions answered from checks and provenance).
- **Expected invoices** schedule.
- `explain_invoice` consult handler (used by Mo in S76-12).
- Every Bernie setting wired.
- **`momentum seed --invoices`** (spec §14.5).
- **Docs:** `docs/agents/bernie.md` (users and admins).
- **Tests:** `test_await_and_learn.py`, `test_converse.py`, `test_profile.py`, `test_expected_invoices.py`.
- **Evals:** `bernie_learn`, `bernie_converse` (≥ 10 mock each).
- **AC:** a correction → approval → proposed skill with a tryout showing the fix; approving it makes the next synth invoice from that vendor clean with no correction.

### S76-12 Coordination: directory cards, plans, consult (L, e2e)
- `GET /agents/directory`; `GET /agents/{key}/card.json` (A2A-shaped, spec §10.1).
- **Migration 0047:** `agent_plans`, `agent_plan_steps`, consumer row `plans`.
- `agents/plans/`:
  - `bindings.py` (parser + type-checker, spec §10.3);
  - the drafter (prompt `agent_planner/v1`, `smart`; code validation; amber fix list);
  - confirm (subtasks, dependencies, assignment, one transaction);
  - the **engine** (outbox consumer; `plan_step` trigger; dedupe per plan version; conditions; agent step completion of its own subtask);
  - failure → owner ask (retry, give to a person, skip, cancel);
  - re-plan (version + 1);
  - budget; limits.
- **Mo:** "Plan with agents" (task menu, Mo panel, chat); Mo as an assignee drafts a plan; "Where is this?"; `ask_agent` tool (consult).
- **Consult** (spec §10.6): read-only, depth 1, billed to the caller, intersected access, timeout.
- Test packs `consultee` and `planner_fixture`.
- **Web:** the plan panel (spec §12.7) with draft edits and live running state.
- **Loop protection extended:** an agent's events never start another agent outside a confirmed plan.
- **Tests:** `test_plans.py`, `test_consult.py`.
- **Evals:** `agent_planner`, `consult` (≥ 10 mock each).
- **e2e:** J23.
- **AC:** J23 green; a plan can't bind a record type no upstream step produces; consult can't write.

### S76-13 Builder kit and docs (M)
- **CLI** (spec §11.1): `packs new` (from `packs/_template/`, editing pyproject and the import contract), `packs check` (complete: asks have defaults, effects used ⊆ declared, injection eval, prompts exist, record schemas valid, determinism lint), `packs run` (interactive asks, `--answers`, `--mock`, `--cleanup`), `packs eval` (`--cases-dir`), `packs golden export` (refuses repo paths), `packs compare bernie` (notebook CSV baseline; live-only use, tested on synth CSVs in mock).
- **SDK testing helpers** (`momentum.sdk.testing`).
- `packs/_template/` and its CI test (scaffold into tmp → check → its tests pass).
- **Docs:**
  - `docs/agents/README.md`;
  - `building-a-pack.md`;
  - `sdk-reference.md` (+ `test_sdk_documented.py`);
  - `porting-a-notebook.md` (Bernie as the worked example);
  - `pack-catalogue.md` (spec §1.1);
  - `docs/ai/agents.md` section "Packs and jobs";
  - `INTEGRATION_GUIDE.md` §6.7 addendum (packs vs `Extensions`, entry points, `MOMENTUM_PACKS`).
- **Tests:** `test_packs_cli.py`.
- **AC:** following only `building-a-pack.md`, `packs new demo --kind pipeline` → `check` → tests → `packs run demo --mock` works end to end.

### S76-14 Exit (M, e2e)
- **e2e:** J20, J21, J22, J24 (complete). The whole suite J1–J24 green twice in a row.
- **J14:** agent page tabs, review screen, Records tab, plan panel, inbox with asks (axe light + dark, keyboard).
- **UI audit and keyboard pass:** `tools/ux/serve.sh` with `seed --invoices` and `MOMENTUM_TEST_PACKS=true`, then `node tools/ux/audit.mjs` and `node tools/ux/keyboard.mjs`. 0 findings; fix anything found and log it in the hardening register as the next H numbers.
- **Full gate:** `make check` + e2e twice + mock evals (`momentum evals`, `momentum packs eval bernie`) all green.
- **Performance:** the 100-invoice mock batch timing; the record query p95 on 50k records (a scale seed variant); write the numbers in the as-built note.
- **Docs:**
  - this file's exit table;
  - STATUS (Phase 7.6 complete, next Phase 8; handoff; retro);
  - the INTEGRATION_GUIDE change log (migrations 0045–0047, packs and the SDK, new routes, events, channels, settings, guest rule for financial records, the loop-protection exception for plans);
  - `asana-vs-momentum.md` ("AI agents" rows);
  - `testing-strategy.md` (J20–J24);
  - the `ai-architecture.md` tool table and prompts.
- **Write § Live verification below as a checklist** with exact commands and clicks.

---

## Live verification (for the product owner, after pulling)

Fill in at S76-14. At minimum:
1. Install and switch Bernie on:
   - `cd apps/api && uv sync && uv run momentum migrate` (0045–0047);
   - `uv run momentum agents install --only bernie`;
   - enable Bernie (Agents → Bernie);
   - add him to a test project and confirm the setup checklist;
   - set Settings → approval tiers and stewards.
2. Run the evals:
   - `uv run momentum llm-check`;
   - `uv run momentum packs eval bernie --live`;
   - `uv run momentum evals --live --feature agent_planner --feature consult --feature ask_interpret --feature records_qa`.

   Every bucket must meet its live threshold. Fix findings with new prompt versions.
3. **Bernie vs the notebook:** `uv run momentum packs compare bernie --files "<COAP_Invoice_Notebook>/sample_invoices or your private invoice folder" --baseline-headers "<COAP_Invoice_Notebook>/output/headers_<run>.csv" --baseline-lines "<COAP_Invoice_Notebook>/output/line_items_<run>.csv"`. Bernie should agree or do better on every field. Read every "differs" row.
4. Clicks:
   - assign a real multi-page invoice;
   - assign a zip organised by vendor folders;
   - answer an ask from the inbox;
   - correct a line on the review screen and approve as the approver;
   - approve the proposed skill (check the before/after);
   - run another invoice from that vendor;
   - `@Bernie why is this on hold?`;
   - on a task, "Plan with agents": "get these invoices extracted and approved by <approver>", then confirm and watch the handoff.
5. **Private golden set:** `uv run momentum packs golden export bernie --status approved --out <a folder outside the repo>`, then `uv run momentum packs eval bernie --live --cases-dir <that folder>`. Keep it for regression runs after every Bernie change.

## As built

(One note per slice, added as each slice lands.)

**S76-00 as built (2026-10-08, local session, real gateway available but unused — this slice is
plumbing only, no AI).** **ADR-0012** (the platform: packs, the SDK facade, durable jobs by
replay, asks, records, entities/skills, D5's plan exception, governance) and **ADR-0013** (Bernie:
D4/D9-D11, no PyMuPDF/Tesseract/Presidio, bank details as fingerprint+last4 only). **Settings**
(spec §13.4): 14 new `MOMENTUM_*` settings in `core/settings.py`, `configuration.md` and
`.env.example` (packs enabled/filter/test-packs, job/step/child/ask/plan/consult ceilings, record
array cap). **Packaging:** `packs/README.md`; `packs/bernie/` (pyproject with the `momentum.packs`
entry point, `momentum_pack_bernie/__init__.py` whose `pack` is a placeholder that imports cleanly
but raises `NotImplementedError` on any real use until S76-01+); `apps/api/pyproject.toml` depends
on `momentum-pack-bernie` via `[tool.uv.sources]` path source (editable); `mypy.packages` and
`pytest.testpaths` (`../../packs`) extended; `ruff`/`mypy` checks (`tools/dev.ps1`, `Makefile`)
pass `--config pyproject.toml` so packs/ is checked under the API's own rules, not its own
(nonexistent) config. `infra/docker/Dockerfile` copies `packs/` to `/packs/` before the first
`uv sync` (the path dependency must exist on disk first). `tests/packs/__init__.py` (empty; the
test-only fixture packs land from S76-02 on). `momentum/sdk/__init__.py`: just `SDK_VERSION =
"1.0"` for now. **Import contracts** (import-linter's `root_packages`, not the old singular
`root_package`, so a pack's own module is a recognised root): a pack may import only
`momentum.sdk`; nothing in momentum statically imports a named pack (the loader discovers packs by
entry point). Both proven with a deliberate bad import that failed `lint-imports`, then removed,
per the slice's own instruction; a permanent regression test for this lands with the loader
(S76-01, matching the spec's own `test_packs_loader.py` grouping). **Found and fixed:** two
pre-existing `forbidden_modules` entries named `momentum.mcp`, a module dropped long before this
phase; `root_package` (singular) never validated forbidden-module names against real modules, but
`root_packages` (needed for the new pack contracts) does, so it surfaced the stale reference.
Removed both. **Gate:** backend lint/format/mypy/import-linter green; `pytest --collect-only`
clean (1,011 tests collected, 0 from `packs/` yet, as expected); the full `pytest -q` run is
S76-00's own gate requirement and is reported in the slice's commit, not re-described here.

## The prompt for the build session

Paste this into the browser session (also correct for resuming after a context reset):

> You are building **Phase 7.6** of Momentum: the agent platform and Bernie, the invoice agent. Read `CLAUDE.md`, then `docs/progress/STATUS.md`, then `docs/roadmap/phase-7.6.md`, the spec it links (`docs/superpowers/specs/2026-10-06-phase-7-6-agent-platform-bernie-design.md`) and `docs/reference/coap-invoice-pipeline/README.md`, in full, before writing code. **If STATUS doesn't show Phase 7.5 as complete, stop and report that.** Otherwise work through the slices in `phase-7.6.md` in order, starting from the first one STATUS doesn't mark done, until the Phase 7.6 exit is complete, without stopping to ask: every product decision is already made in the spec (D1–D12) and the phase file, and anything not covered is yours to decide by the spec's principles and record in STATUS under "Decisions (Phase 7.6, delegated)". There is **no AI gateway** in this environment: use `MOMENTUM_LLM_MODE=mock` for everything; every AI feature needs handwritten mock fixtures and mock eval cases at 1.0, and live-only cases written for later. Real invoices never enter the repo: use the synthetic generator. Packs import only `momentum.sdk`; add no new dependencies (never PyMuPDF, Tesseract or Presidio). Follow the "Working rules for the build session" in `phase-7.6.md` exactly: the full gate green per slice (it includes `packs/`), docs in the same slice, one commit per slice (`Phase 7.6 S76-NN: …` with the Co-Authored-By line), `git fetch` + rebase and push to `main` after each green slice (never force-push, never push red), and update STATUS (checkbox, date, result, next up, handoff) after every slice so a new session can resume from it. Finish by completing S76-14 (exit table, live verification checklist, INTEGRATION_GUIDE change log) and reporting what was built, the gate results and anything deferred.
