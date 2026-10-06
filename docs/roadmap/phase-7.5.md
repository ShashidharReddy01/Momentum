# Phase 7.5: Files, reports, lifecycle portfolios and dashboards, and Mo

> **Added 2026-10-06 by the product owner**, between Phase 7 (Hardening, done) and Phase 8 (Azure go-live). Design: `docs/superpowers/specs/2026-10-06-phase-7-5-ai-files-insight-design.md` (**the spec**; section numbers below like "spec §4.5" point into it). Read the spec fully before the first slice.

**Goal:** Momentum handles the files people really use, produces real reports, and shows a customer lifecycle (pre-sales → discovery → contracts → implementation → go-live → hypercare) the way each role needs to see it, with Mo helping on request. It should be clearly better than Asana for the ~150 people moving over.

**How this phase is built:**
- **Where:** a separate browser session (Claude Code on the web). **There is no AI gateway there.** Build and test everything with `MOMENTUM_LLM_MODE=mock`: every AI entry point has handwritten mock fixtures and mock eval cases at threshold 1.0, and the e2e journeys run on mock AI.
- **Live checks:** live-only eval cases are written now. The product owner runs them after pulling (§ Live verification).
- **Decisions are made:** the spec's D1–D8 and every choice written here are final. **Don't stop to ask.** When something isn't covered, pick what fits the spec's principles (data honesty, one write path, visibility first, nothing on upload, numbers from the server, preview → confirm → apply → undo). Then record it in STATUS under "Decisions (Phase 7.5, delegated)" and in the slice's as-built note.

**Exit criteria:**
- Every slice below done with its tests. `make check` green.
- e2e: J1–J19 green twice in a row (J15–J19 new).
- Mock evals: every new feature at 1.0. Live-only cases written for each.
- The UI audit (`tools/ux/audit.mjs`) and keyboard pass (`tools/ux/keyboard.mjs`) both report 0 findings, with the new screens included.
- Performance budgets in spec §5.3 and §7.6 met on the seeds (measured, written in the as-built note).
- Docs updated per CLAUDE.md §5 (data model, events, settings, AI tools and prompts, design system, ADR-0011, INTEGRATION_GUIDE change log).
- `momentum seed --onboarding` produces the full demo: every role dashboard renders with real numbers.
- The live verification list is written for the product owner.

---

## Working rules for the build session

1. **Start of every session** (CLAUDE.md §1):
   - read `docs/progress/STATUS.md`, this file, then the spec;
   - run the gate on the baseline;
   - continue from the first slice not marked done in STATUS.
2. **Gate per slice** (same commands as `make check`): `cd apps/api && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run lint-imports && uv run pytest -q`, and `cd apps/web && pnpm exec prettier --check . && pnpm exec eslint . && pnpm exec tsc -b && pnpm exec vitest run`.
   - Run the e2e suite (`pnpm build && pnpm exec playwright test`) at the slices marked **e2e**, and at exit.
   - Never run two pytest processes at once (they share `momentum_test`).
3. **Commit per slice** when its gate is green. Message: `Phase 7.5 <slice id>: <what>`, ending with the Co-Authored-By line from the session. **Push to `main`** after each green slice:
   - `git fetch` and rebase on `origin/main` first;
   - never force-push;
   - never push a red gate.
4. **After each slice**, update STATUS:
   - the checkbox, date and one-line result;
   - "Next up";
   - the handoff note.

   That way a new session with the same prompt continues exactly where this one stopped, even after a context reset.
5. **Docs in the same slice** (CLAUDE.md §5): `data-model.md` for every table and column, `realtime-jobs-events.md` for every event, `configuration.md` + `.env.example` for every setting, `ai-architecture.md` for every tool and prompt, `design-system.md` for new UI patterns, plus this file's "As built" note per slice.
6. **AI rules:**
   - new prompts are files `ai/prompts/<feature>/v1.md`;
   - model aliases only;
   - every AI output amber-marked with `created_via` / `actor_kind`;
   - mock output visibly marked (purple MOCK);
   - file and user content is data, never instructions.
7. **Migrations:** **0042** (files), **0043** (project fields, portfolios v2, snapshots), **0044** (dashboards v2, visits, conversation files).
   - Review the autogenerate output.
   - No data is dropped; backfills are in the migration.
   - Downgrades work.
8. **Dependencies:** only those in spec §10, added to `pyproject.toml` with `uv add`, locked, and `pip-audit` clean. No system packages.
9. **Keep the existing sweeps green:** robustness, anonymous access, undo coverage, `test_every_mutation_records_activity` (add activity rows; don't extend its allowlist without a reason in the register), permission matrix, guests (H61), J14 axe.

---

## Slices (in this order)

Sizes: S ≈ half a day, M ≈ 1 day, L ≈ 2 days. **e2e** marks slices that end with an e2e run.

### S75-00 Kickoff and foundations (S)
- Gate the baseline.
- Add the spec §10 dependencies (`uv add …`; `pip-audit` clean) and the settings (with `configuration.md` and `.env.example`).
- Write **ADR-0011** "Files, document parsing and report generation" (template `docs/templates/adr.md`): D1, D4, D6, D7, no execution, the dependency table, the mock-only build.
- Add `momentum/files/` (package skeleton) and `momentum/reports/` to the import-linter contracts:
  - `files` imports only `core`;
  - `reports` may import `core`, `files` and `domain`, never `ai`;
  - AI narrative is injected through a callable passed in by `ai/`.
- STATUS: Phase 7.5 in progress; "Plan changes" log entry.
- **AC:** gate green; ADR merged; contracts enforced (a deliberate bad import fails `lint-imports`, then is removed).

### S75-01 Files: data model, inventory, project uploads, versions (L, e2e)
- **Migration 0042, part 1:** the `attachments` columns and constraint from spec §3.1 with backfill.
- **Attachments service:**
  - `upload_project_file`;
  - new versions (`replace_id`), undo restores the previous current;
  - delete promotes the previous version;
  - `list_project_files` (visibility: project files, tasks at any depth, comments);
  - versions listing.
  - Activity: `attachment.created` / `attachment.version_added` / `attachment.deleted` with undo.
  - Events: `attachment.added` (existing) and `attachment.version_added` (new, catalogued).
- **API:** `POST /projects/{id}/files`, `GET /projects/{id}/files`, `GET /attachments/{id}/versions`; the existing attachment upload gains `replace_id`.
- **Search:** a `files` group (name + `text_extract`), visibility-filtered.
- **Portability:** the export/import bundle carries the new columns; the round-trip test stays byte-identical.
- **Web:**
  - Project tab **Files** (spec §3.3): table (grid pattern, roving focus), filters, search, drag-and-drop and Upload, preview drawer (image, sandboxed PDF iframe, safe text/markdown, metadata);
  - "Upload as new version?" prompt, versions drawer, delete with Undo toast;
  - **Ask Mo about this file** button: opens Mo with a file chip; wired to S75-03; until then it opens Mo with the chip only.
- **Tests:**
  - API: `test_files_inventory.py` (spec §11.2), permission rows (viewer/editor/guest/outsider), undo round-trips in `test_undo_coverage.py`;
  - web: `files.test.tsx` (list, filter, upload, version prompt, delete + undo);
  - e2e: **J15 part 1** (upload to the project, see a task's file, new version, versions, delete + undo).
- **AC:** every visible file of a project is listed exactly once (current versions); a private task's file never appears to a non-member or a guest; J15 part 1 green; robustness and anonymous sweeps green.

### S75-02 File parsing: DocumentModel, parsers, cache, safety (L)
**No AI in this slice.**
- **Code:**
  - `files/model.py` (spec §4.1);
  - `files/parsers/*` per format (spec §4.2 table, including macros via olevba and email via stdlib / extract-msg);
  - `files/safety.py` (spec §4.6);
  - `files/tables.py` (TableQuery, spec §4.5);
  - `files/render.py` (PDF page and image → JPEG within caps, EXIF stripped).
- **Cache:** the `file_parses` table (migration 0042 part 2) and `files/cache.py`, with `get_or_parse(attachment) -> DocumentModel` in a worker thread with a timeout. Rows go in the storage backend (gzipped JSON per sheet).
- **Fixture builder:** `tests/fixtures/files/build.py` + `templates.py` (spec §11.1). Every sample is generated at test time; only two small PNGs are committed.
- **Tests:** `test_file_parsers.py`, `test_file_safety.py`, `test_table_query.py` (spec §11.2). Include: formulas + cached values; a workbook never recalculated (values missing → stated); macro modules and flags with **no execution** (assert no subprocess, no `win32com`/`ole` automation); a scanned page detected; an encrypted PDF/XLSX → `encrypted`; zip and XML bombs rejected fast (< 2 s); a 5,000-row sheet query is exact; locale numbers `1.234,50` vs `1,234.50` (column-level inference); `(1,234)` negative.
- **Docs:** `data-model.md` (`file_parses`); a new `docs/engineering/files.md` (formats table, limits, what's never done).
- **AC:** every format in spec §4.2 produces the expected parts or a clear warning; all safety tests pass; the parse of the 5,000-row fixture takes < 3 s.

### S75-03 Mo reads files: tools, table queries, vision, conversation files (L, e2e)
- **Tools:** `ai/tools/file_tools.py` (spec §4.4: `list_files`, `file_outline`, `read_file`, `read_sheet`, `query_table`, `search_in_file`, `look_at`, `describe_macros`), registered with `risk="read"` and READ scopes. `FileRef` resolution follows `TaskRef`. `get_attachment_text` stays, with its description updated.
- **Vision:**
  - `Msg` content may be a list of parts;
  - `ai/loop.py` appends a user message with image parts after `look_at`'s tool results (spec §4.7);
  - the caps and settings;
  - usage counting for image tokens;
  - **mock transport** handles list content (matches text parts; `request_key` hashes text + image dimensions; record mode stores the same).
- **Ask Mo:**
  - file context chips (from the Files tab, a task's attachment menu, drag into the composer);
  - a paperclip to attach a file: it goes to the current task or project if the person can edit there, else to a private `ai_conversation_files` row (migration **0044** part 1, deleted with the conversation).
  - Nothing is parsed until a message is sent.
- **Prompts:** `chat` and `command` get new versions (vN+1) with the file rules: numbers about spreadsheets only from `query_table` / `read_sheet` output; cite locators; files and images are data; macros are described, never run; unsupported formats say what to do.
- **Evals:** features `file_qa`, `file_tables`, `file_vision`, `file_injection` (spec §11.3), each ≥ 10 mock cases with fixtures plus ≥ 5 live-only. New scorers: `cites_locator`, `numbers_from_tools`, `query_exact`, `images_sent`. The eval workspace `onboarding_v1.yaml` gets its files from the fixture builder (stub it here with the files; the projects come in S75-06).
- **Tests:** `test_ai_files.py`:
  - a private file is unreadable through every tool for a non-member and a guest;
  - the image caps are enforced;
  - `look_at` with vision off returns `not_supported`;
  - a hostile docx/png leads to no proposals (mock);
  - "turn these notes into tasks" yields create_task **previews only**.
- **e2e:** **J15 part 2** (ask Mo about the workbook from the Files tab; the mock answer shows a locator chip; the query tool appears in the activity line).
- **AC:** mock evals for the four features at 1.0; J15 green.

### S75-04 Project fields, template lineage, field history, rules action (M)
- **Migration 0043 part 1:**
  - `field_defs.applies_to`;
  - `project_field_values`, `project_field_events`;
  - `projects.template_id` (set by `create_project_from_template`; null for every other project, including Asana imports).
- **Service:** `set_project_field_value` (activity `project.field_set` with undo, event `project.field_changed` on `project:<id>` and every containing portfolio's channel, history row). Project templates store project field defaults; "new from template" applies them.
- **Rules:** a new action `set_project_field` (builder UI, engine, NL rule prompt `nl_rule/vN+1` with fixtures, gate-aware per spec §5.5).
- **Web:** the project Overview gets a **Details** card (edit project fields; empty states); field library management shows "Applies to: Tasks / Projects".
- **Tests:** `test_project_fields.py` (every type, history rows, undo, permissions, events, the template default, the rule action incl. gate skip).
- **AC:** setting a project field via UI, API, rule or Mo-tool path writes exactly one history row and one undoable activity.

### S75-05 Portfolio v2 backend: rules, stage, columns, views, gates, snapshots (L)
- **Migration 0043 part 2:**
  - portfolio columns `kind`, `rule`, `stage_field_id`, `stage_targets`, `stage_gates`, `columns`;
  - `portfolio_views`, `portfolio_members`, `project_snapshots`.
- **Service:**
  - rule membership as the viewer;
  - `portfolio_rows` with every built-in column (spec §5.3) in SQL, without N+1 (assert the query count in tests);
  - grouping and rollups;
  - views CRUD (personal and shared);
  - members and permissions (spec §5.6);
  - convert manual ↔ rule;
  - readiness (spec §5.5);
  - a stage change via the board = `set_project_field_value`, plus a gate check with an explicit `override=true` recorded in the activity.
- **Workload:** the service accepts `project_ids`.
- **Snapshots:** the nightly job `snapshot_projects` (02:45), the `momentum snapshots backfill --days N` CLI and retention.
- **API:** `/portfolios` v2 endpoints (rows with view params, views CRUD, members, readiness, columns). Existing endpoints and tests keep working.
- **Tests:** `test_portfolio_v2.py`, `test_snapshots.py`, and the permission matrix extended with portfolio roles.
- **AC:** the 40-project onboarding portfolio (S75-06) returns rows in < 300 ms locally; the query count is constant in the project count; guests see only shared rows.

### S75-06 Customer onboarding template, seed and eval workspace (M)
- **Template "Customer onboarding"** (shipped as seed data and also offered in the template gallery):
  - **Sections and tasks** (≈ 36 tasks; owners as template roles):
    - **Pre-sales:** Qualify opportunity; Demo; Proposal; Pricing approval.
    - **Discovery:** Kickoff call; Current-state workshop; Requirements doc; Solution design; *Discovery complete* (milestone).
    - **Contracts:** Draft SOW; Quote; Legal review; Customer redlines; *Contract signed* (milestone).
    - **Implementation:** Implementation kickoff (milestone); Environment setup; Data migration plan; Configuration; Integrations; Training plan; UAT plan; UAT; *UAT sign-off* (milestone).
    - **Go-live:** Cutover plan; Go/no-go meeting; *Go-live* (milestone); Post-go-live check.
    - **Hypercare:** Daily check-ins; Issue log review; *Hypercare exit* (milestone).
    - **RAID:** Risks, Assumptions, Issues, Decisions as tasks with the field.
  - **Task fields:** Waiting on (Customer / Internal / Third party); RAID type (Risk / Assumption / Issue / Decision); Severity (High / Medium / Low).
  - **Project fields:**
    - Stage (Pre-sales, Discovery, Contracts, Implementation, Go-live, Hypercare, Live, Lost, On hold);
    - Account owner (people), Contract value (currency), Region (EMEA / North America / APAC / LATAM), Target go-live (date), Products (multi-select: Core, Analytics, Integrations, Mobile).
  - **Rules:**
    - *Discovery complete* done → Stage = Contracts;
    - *Contract signed* → Implementation;
    - *UAT sign-off* → Go-live;
    - *Go-live* → Hypercare;
    - *Hypercare exit* → Live.
- **Portfolio "Customer onboarding"** (rule: template = Customer onboarding):
  - stage field Stage; targets (days): Pre-sales 30, Discovery 21, Contracts 14, Implementation 90, Go-live 14, Hypercare 30;
  - **gates:**
    - Implementation needs Contract value set + *Contract signed* done + a file matching `*signed*`;
    - Go-live needs *UAT sign-off*;
    - Live needs *Hypercare exit*.
  - Default columns: name, Stage, Account owner, Contract value, status, progress, stage age, target, forecast, slip, next milestone, waiting on customer.
- **`momentum seed --onboarding`** (synthetic, deterministic `random.Random(75)`, idempotent):
  - **Personas:** adds Sofia Reyes (sales AE) and Dev Patel (discovery consultant); uses Lena Novak (contracts), Ravi Kumar (implementation lead), Mei Chen and Tom Becker (consultants), Sam Okafor (go-live/support) and Avery Admin (leadership).
  - **Customers:** 40 synthetic companies across stages: Pre-sales 8, Discovery 6, Contracts 5, Implementation 10, Go-live 3, Hypercare 3, Live 3, Lost 1, On hold 1.
  - **History:** six months of stage history in `project_field_events`, with durations around the targets and some breaches.
  - **Work state consistent with stage:** earlier sections done; some projects slipping (forecast past target); waiting-on-customer tasks; open RAID items; files from the fixture builder (SOW .docx, quote .xlsx, signed contract .pdf, kickoff .pptx, a screenshot .png); comments; status updates.
  - **Then:** a snapshot backfill, and the seven role dashboards (S75-08) pinned to each persona's Home.
- **Eval workspace** `ai/evals/fixtures/workspaces/onboarding_v1.yaml`: 12 customers drawn from the same generator (smaller), the lifecycle portfolio, files and a hostile file.
- **Tests:** `test_seed_onboarding.py` (counts per stage, gates consistent, rules fire on the template, deterministic).
- **AC:** a fresh DB + `seed --onboarding` gives a portfolio whose board shows every stage with the counts above; re-running it adds nothing.

### S75-07 Portfolio v2 web (L, e2e)
- **`features/portfolios/`:** the portfolio page with tabs **Table · Board · Timeline · Workload · Dashboard · Reports** (spec §5.4):
  - the saved-views switcher (personal / shared);
  - column picker;
  - group-by with rollup rows;
  - inline edit of project fields;
  - bulk "Set field…" (one undo);
  - CSV export of the view.
- **Board:** drag sets Stage with the readiness checklist dialog (spec §5.5); "Move anyway" is for editors and is recorded.
- **Timeline:** bars, forecast cone, milestones, today line; group by stage or owner; month/quarter zoom.
- **Portfolio settings dialog:** manual / rule, rule builder (templates, teams, project field conditions), stage field and targets, gates editor, members.
- **Portfolio list page:** cards with stage mini-bars (count per stage) and total value.
- **Design system:** document the spreadsheet table, rollup rows and stage card patterns in `design-system.md`.
- **Tests:** web unit tests per layout; **J16** (spec §11.4); J14 adds the portfolio table and board pages (axe + keyboard: the board is operable with the keyboard (move card via a menu "Move to stage…"), as the board view already is).
- **AC:** J16 green; the UI audit adds the portfolio pages at all viewports with 0 findings.

### S75-08 Dashboards v2: query, widgets, filters, templates (L, e2e)
- **Backend:**
  - QuerySpec v2 (spec §7.1) with entities `tasks` (+`split_by`, `portfolio_id`), `projects` (+ filters `slipping`, `has_blocked`, `has_waiting_on_customer`), `stage_events` (`funnel`, `time_in_stage`, `throughput`, `aging`) and `snapshots`;
  - `query.py` split per entity behind `run_query`;
  - widget kinds (spec §7.2);
  - dashboard filters + `me` (spec §7.3);
  - `dashboard_members` (migration 0044 part 2);
  - the result cache (spec §7.6);
  - drill for projects and stage events;
  - **every v1 test keeps passing unchanged**.
- **Role templates:** `domain/dashboards/templates/*.yaml` with exactly these widgets (titles as shown; specs per spec §7). Binding by name, with dropped-widget notes (spec §7.5).
  - **Sales** (filters: portfolio; Account owner = me):
    1. KPI *My pipeline value* (sum Contract value, Stage ∈ Pre-sales…Contracts);
    2. KPI *Accounts in flight* (Stage ∉ Live, Lost);
    3. bar *Value by stage*;
    4. aging *Deal aging* (Pre-sales, Discovery, Contracts);
    5. table *My accounts* (name, Stage, stage age, next milestone, Target go-live, Contract value, status);
    6. timeline *Go-lives, next 90 days*;
    7. KPI *Went live this quarter* (throughput into Live, vs last quarter);
    8. list *My tasks due in 14 days*.
  - **Discovery:**
    1. list *My discovery tasks this week*;
    2. aging *Discovery aging vs 21 days*;
    3. table *Discoveries in flight* (name, owner, stage age, waiting on customer, next milestone);
    4. KPI *Median discovery time (90 days)*;
    5. bar *Waiting on customer by customer*.
  - **Contracts:**
    1. table *Contracts queue* (name, Account owner, stage age, Contract value, waiting on customer);
    2. stacked bar *Contract tasks by customer, split by Waiting on*;
    3. KPI *Signed this month* (vs last month);
    4. stage time *Time to signature vs 14 days*;
    5. KPI *Value awaiting signature*.
  - **Implementation lead** (filters: portfolio; project owner = me):
    1. KPI *Active implementations*;
    2. KPI *Slipping* (forecast past target);
    3. table *Control tower* (name, status, progress, Target go-live, forecast, slip, next milestone, blocked, waiting on customer, stage age);
    4. timeline *Go-lives, next 90 days*;
    5. bar *Waiting on customer, open tasks by customer*;
    6. stacked bar *Open RAID by customer, split by Severity*;
    7. line *Overdue tasks per week across my implementations (12 weeks, snapshots)*;
    8. bar *Consultant load: open tasks by assignee*.
  - **Implementation consultant** (assignee = me):
    1. list *My tasks due this week, across customers*;
    2. bar *My open tasks by customer*;
    3. list *My blocked tasks*;
    4. KPI *Completed this week* (vs last week);
    5. timeline *Milestones in my projects, next 30 days*.
  - **Go-live & support:**
    1. timeline *Go-lives, next 30 days*;
    2. table *Go-live readiness* (Stage = Go-live: name, Target go-live, progress, blocked, next milestone);
    3. bar *Hypercare issues by customer* (RAID type = Issue, Stage = Hypercare);
    4. KPI *Went live this month*;
    5. aging *Hypercare aging vs 30 days*.
  - **Leadership:**
    1. funnel *Lifecycle funnel (180 days)*;
    2. stage time *Time in stage vs target*;
    3. bar *Value by stage*;
    4. line *Go-lives per month (12 months)*;
    5. KPI *Revenue in flight* (Contracts…Go-live);
    6. table *Customers at risk* (status at risk / off track, or slipping);
    7. aging *All stages*;
    8. bar *Customers by region*.
- **Web:**
  - widget renderers for `kpi` (delta, target ring), `stacked_bar`, `table`, `funnel`, `stage_time`, `aging`, `timeline`, `note`;
  - the editor supports entity choice and the new fields;
  - the filter bar (period presets, portfolio, owner = me, project fields) with "view for me" vs "save" (editors);
  - the template gallery ("New dashboard → From a template", bind to a portfolio, preview with dropped-widget notes);
  - pin to Home (per user, Home shows pinned dashboards as a section);
  - the portfolio Dashboard tab.
- **Tests:** `test_dashboards_v2.py`, `test_stage_analytics.py` (spec §11.2), web unit tests per widget, **J17** (the export part runs after S75-09; until then J17 stops after the drill).
- **AC:**
  - each of the seven templates instantiated on the seeded portfolio shows every widget with non-empty, correct data for its persona;
  - a known-answer test per stage analysis passes;
  - a 10-widget dashboard is < 1.5 s p95 on the onboarding seed (measured locally with the E7.1 method; numbers in the as-built note).

### S75-09 Reports engine (L, e2e)
- **Code:**
  - `reports/spec.py`, `reports/document.py`;
  - builders per kind (spec §6.2) using domain queries **as the requester**;
  - renderers docx / xlsx / pdf / md / csv (spec §6.1; bundled DejaVu fonts; formula-safe xlsx; AI paragraph markers);
  - the job, storage as an attachment (`source='generated'`, `generated_spec`), activity `report.generated` with undo, regenerate as a new version.
- **AI narrative:** `ai/report_narrative.py` (prompt `report_narrative/v1`, structured output with `cites`; uncited paragraphs dropped), injected into the builders from `ai/` (reports must not import ai).
- **Mo tool:** `generate_report` (`risk="low"`, preview → confirm → apply → undo; the preview shows the outline).
- **API:** `POST /reports/preview`, `POST /reports`, `GET /reports/jobs/{id}`.
- **Web:** the "Create report" dialog on the project, portfolio and dashboard menus; a progress toast; files appear in Files / Reports with the badges.
- **Evals:** `report_narrative` (≥ 10 mock, ≥ 5 live-only).
- **Tests:** `test_reports.py` (every kind × format; re-open the files with their libraries and assert the values equal the domain numbers; customer audience hides internal; Unicode), `test_ai_reports.py`, **J18**, and J17's export step.
- **AC:**
  - every kind renders in every allowed format;
  - opening the .docx/.xlsx/.pdf with python-docx / openpyxl / pdfplumber shows the same KPI values the dashboard and portfolio show;
  - narrative paragraphs carry the AI marker;
  - a customer report never contains a task tagged `internal`.

### S75-10 Mo on portfolios and dashboards (L)
Spec §8, all on request:
- read tools `get_portfolio_rows`, `get_stage_metrics`;
- **Portfolio brief** (button + Ask Mo; "Post as status update" via preview);
- **Ask the portfolio** (NL → portfolio view filters; shares S75-11's filter engine; build that engine here if S75-11 isn't done, and S75-11 reuses it);
- **Dashboard from a sentence** (`DashboardDraft` → preview with real numbers → create);
- **Explain this chart**;
- **Readiness check** (+ optional file reading when ticked);
- **Handoff note** (offered after a stage change; a preview posted as a status update or comment).

Prompts: `portfolio_brief/v1`, `dashboard_draft/v1`, `explain_chart/v1`, `handoff/v1`. Evals `portfolio_brief`, `dashboard_draft`, `explain_chart`, `handoff` (≥ 10 mock each, ≥ 5 live-only). Tests: `test_ai_portfolio.py` (visibility: a brief never mentions a project the viewer can't see; numbers only from tools; nothing is written without confirm).
- **AC:** all four evals at 1.0 in mock.

### S75-11 Catch me up and Plain-English filters (M, e2e)
- **Catch me up** (spec §9.1):
  - `user_visits` (migration 0044 part 3);
  - the visit beacon;
  - `POST /ai/catch-up` with **no model call when nothing changed**;
  - the Home card, project and portfolio buttons, ⌘K entry;
  - prompt `catch_up/v1`.
- **Plain-English filters** (spec §9.2):
  - `POST /ai/filters` for the surfaces list / board / calendar / My Tasks / search / portfolio views;
  - the filter bar input, chips and Apply, the amber marker;
  - prompt `filters/v1`.
- **Evals:** `catch_up` (≥ 10 mock incl. "nothing changed → no call"), `nl_filters` (≥ 20 mock, `filters_exact`), live-only ≥ 5 each.
- **Tests:** `test_ai_catch_up.py`, `test_ai_filters.py` (unresolvable names asked back with real options; relative dates in the viewer's timezone; visibility).
- **e2e:** J19 parts 1–2.

### S75-12 Smart task creation and project close-out (M, e2e)
- **Smart task creation** (spec §9.3; **no LLM**):
  - `POST /ai/task-suggestions`;
  - duplicates (embedding ≥ 0.86 or trigram ≥ 0.6);
  - assignee, due, field and tag suggestions with reasons and thresholds;
  - the setting and the per-user preference;
  - the UI in quick add, the add-task row and the new task pane;
  - J19 part 3.
- **Close-out** (spec §9.4): the toast on complete / archive, the menu item, the `closeout` report kind (built in S75-09; verify here end to end), the status-update-from-summary preview. Evals `closeout` (≥ 10 mock).
- **Tests:** `test_task_suggestions.py` (thresholds exact on constructed data; inactive / agent assignees never suggested; private tasks never offered as duplicates).

### S75-13 Exit (M, e2e)
- **J14:** add the Files tab, the portfolio table / board, a v2 dashboard and the report dialog (axe light + dark, keyboard).
- **UI audit and keyboard pass:** run `tools/ux/serve.sh` with `seed --onboarding` added to the script (and `--showcase`), then `node tools/ux/audit.mjs` and `node tools/ux/keyboard.mjs`. 0 findings; fix anything found and log it in the hardening register as H64+.
- **Full gate:** `make check` + e2e twice + mock evals (`momentum evals`) all green.
- **Performance:** run the portfolio rows, dashboard and report timings on the onboarding seed and write the numbers in the as-built note.
- **Docs:**
  - this file's exit table;
  - STATUS (Phase 7.5 complete, next Phase 8; handoff);
  - INTEGRATION_GUIDE change log (migrations 0042–0044, new routes and events, settings, dependencies, the reports/files packages, guest rules unchanged);
  - `asana-vs-momentum.md` (portfolios / dashboards / reports / files rows);
  - `testing-strategy.md` (J15–J19);
  - `docs/ai/ai-architecture.md` tool table and prompts.
- **Write § Live verification below as a checklist** with exact commands and clicks.

---

## Live verification (for the product owner, after pulling)

Fill in at S75-13. At minimum:
1. `cd apps/api && uv sync && uv run momentum migrate` (0042–0044), then `uv run momentum seed --onboarding`, `uv run momentum snapshots backfill --days 180` and `uv run momentum llm-check` (vision row must pass).
2. `uv run momentum evals --live --feature file_qa --feature file_tables --feature file_vision --feature file_injection --feature report_narrative --feature catch_up --feature nl_filters --feature dashboard_draft --feature portfolio_brief --feature explain_chart --feature handoff --feature closeout`. Every bucket must meet its live threshold. Fix findings with new prompt versions.
3. Clicks:
   - attach your own real files (an .xlsm with macros, a scanned contract, a screenshot, an Outlook .msg) to a task and ask Mo about each;
   - generate every report kind and open each in Word, Excel and a PDF reader;
   - sign in as each seed persona (Sofia, Dev, Lena, Ravi, Mei, Sam, Avery) and walk their pinned dashboard;
   - drag a customer across a gated stage;
   - ask Mo "brief me on onboarding" and "build me a dashboard for my implementations".

## As built

(One note per slice, added as each slice lands.)

## The prompt for the build session

Paste this into the browser session (also correct for resuming after a context reset):

> You are building **Phase 7.5** of Momentum. Read `CLAUDE.md`, then `docs/progress/STATUS.md`, then `docs/roadmap/phase-7.5.md` and the spec it links (`docs/superpowers/specs/2026-10-06-phase-7-5-ai-files-insight-design.md`) in full before writing code. Work through the slices in `phase-7.5.md` in order, starting from the first one STATUS doesn't mark done, until the Phase 7.5 exit is complete, without stopping to ask: every product decision is already made in the spec (D1–D8) and the phase file, and anything not covered is yours to decide by the spec's principles and record in STATUS under "Decisions (Phase 7.5, delegated)". There is **no AI gateway** in this environment: use `MOMENTUM_LLM_MODE=mock` for everything; every AI feature needs handwritten mock fixtures and mock eval cases at 1.0, and live-only cases written for later. Follow the "Working rules for the build session" in `phase-7.5.md` exactly: the full gate green per slice, docs in the same slice, one commit per slice (`Phase 7.5 S75-NN: …` with the Co-Authored-By line), `git fetch` + rebase and push to `main` after each green slice (never force-push, never push red), and update STATUS (checkbox, date, result, next up, handoff) after every slice so a new session can resume from it. Finish by completing S75-13 (exit table, live verification checklist, INTEGRATION_GUIDE change log) and reporting what was built, the gate results and anything deferred.
