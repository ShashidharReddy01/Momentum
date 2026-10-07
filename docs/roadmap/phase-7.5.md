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
  - STATUS (Phase 7.5 complete, next Phase 7.6 (`phase-7.6.md`); handoff);
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

**S75-00 as built (2026-10-06).** ADR-0011 (`docs/adr/0011-files-parsing-and-reports.md`). Runtime dependencies added with `uv add` and locked: openpyxl 3.1.5, xlrd 2.0.2, python-pptx 1.0.2, pdfplumber 0.11.10, pypdfium2 5.14.0, Pillow 12.3.0, oletools 0.60.2, extract-msg 0.56.1, striprtf 0.0.33, defusedxml 0.7.1, reportlab 5.0.1; `pip-audit` on the exported runtime requirements: no known vulnerabilities. Nine settings (spec §10) in `core/settings.py`, `configuration.md` and `.env.example`. Packages `momentum/files/` (with `parsers/`) and `momentum/reports/` (with `builders/`, `render/`, `fonts/` holding DejaVu Sans regular and bold plus the license). Two import-linter contracts: `files` imports only `core`; `reports` never imports `ai`, `agents`, `integrations` or app wiring. Checked by adding `from momentum.ai import llm` to each package: `lint-imports` reported the contract broken, then the line was removed.

**S75-01 as built (2026-10-06).** Migration **0042** (`0042_s75_files.py`): the `attachments` columns, constraint and backfill of spec §3.1, plus `file_parses` (spec §4.3) and `ai_conversation_files` (spec §4.8) created here rather than in 0044 (decision D75-5), and `projects.default_view` may be `files`. Service (`domain/attachments/service.py`): one `create_attachment` for every owner (task, comment, project, portfolio) with `replace_id` for a new version (same place only; the version number is max + 1 in the group), `upload_project_file`, `list_versions`, `get_visible_attachment` for readers outside the module; `_recompute_current` keeps exactly the newest live version current after every add, delete and restore, so deleting the current version promotes the previous one and every undo order is consistent. Activity `attachment.created` / `attachment.version_added` / `attachment.deleted` (each undoable); events `attachment.created` / `attachment.version_added` / `attachment.deleted` / `attachment.restored` on `task:`, `project:` or `portfolio:` channels. Inventory (`domain/attachments/inventory.py`): one SQL query over a recursive CTE of the project's live tasks at any depth (a deleted task hides its subtree), the project's own files and live comments' files, with the file kind computed in SQL from the same table as `files/kinds.py`, filters `q` (name or extracted text, `ILIKE` with escaping), `kind`, `where`, `source`, `uploaded_by`, sorts newest / name / size, an offset cursor of 50, a `total`, and per row the uploader's name, the version count and the location (task key and title, comment). API: `POST /projects/{id}/files` (multipart, optional `replace_id`), `GET /projects/{id}/files`, `GET /attachments/{id}/versions`; the task and comment upload routes take `replace_id` too. Search: a `files` group (type `file`) of current files on visible projects, their top-level tasks and comments. Portability needed no change (the export is generic over the metadata; the round-trip test passes). Web: `features/files/` (`FilesView`, queries), a **Files** tab, the search page and ⌘K show files, `MoContext` gains `file` (the "Ask Mo about this file" chip; the file itself travels with the question from S75-03). Found and fixed: **H64** (P1), every upload on a server with a job worker returned 500 because the extraction job was looked up under its Procrastinate 2 name. Tests: `test_files_inventory.py` (7), a project-files permission matrix (admin/editor/commenter/viewer/outsider), three undo-coverage rows, the H64 job-name check, `files.test.tsx` (6), **J15 part 1** (e2e).

**S75-02 as built (2026-10-06).** No AI. `momentum/files/`: `model.py` (DocumentModel, `PARSER_VERSION = 1`, rows kept apart in `ParseResult.rows`), `parse.py` (`parse_bytes`: safety checks, then one parser per family; every failure becomes a status (`failed`, `unsupported`, `encrypted`) with a plain-English warning, never an exception), `parsers/` (`word`, `sheets`, `slides`, `pdf`, `images`, `text`, `email`, `archive`), `macros.py` (olevba as text; flags reduced to five plain meanings, olevba's analysis backed by our own word scan, one flag per meaning), `safety.py`, `values.py` (per-column number/date inference), `tables.py` (`TableQuery`, `run_query`), `render.py` (pypdfium2 pages and Pillow images to capped JPEGs with no metadata; pictures embedded in .docx/.pptx), `cache.py` (`get_or_parse` in a worker thread with the timeout; the model in `file_parses`, rows gzipped in storage; `on conflict do nothing` for concurrent first reads). Deleting an attachment drops its parse. **Samples** (`momentum/files/samples/`, re-exported by `tests/fixtures/files/build.py`): every format generated at run time, including real VBA projects (an OLE compound-file writer plus an MS-OVBA writer using literal tokens), a BIFF8 .xls, an Outlook .msg and workbooks with cached formula results; nothing binary committed (decision D75-12). Measured: the 5,000-row workbook parses in ~1.2 s (AC < 3 s; asserted in `test_table_query.py`); bombs are refused in < 0.2 s. Tests: `test_file_parsers.py` (16), `test_file_safety.py` (9), `test_table_query.py` (16), `test_file_cache.py` (2). Docs: `docs/engineering/files.md`.

**S75-03 as built (2026-10-06).** **Tools** (`ai/tools/file_tools.py`, all `risk="read"`, in the catalog): `list_files`, `file_outline`, `read_file`, `read_sheet`, `query_table`, `search_in_file`, `look_at`, `describe_macros`; `FileRef` is an id or a name (optionally within a task or project) resolved through the download gate or the person's own chat files, never guessing (several matches give candidates). `ai/file_context.py`: `FileSession` (the conversation's chips and uploads, the screen's task/project, images pending for the next call, images sent so far), `visible_files`, `chat_files`. **Vision:** `look_at` renders (S75-02 `render.py`) and queues images; `loop.py` sends them as one user message after the step's tool results (`images_message`, marked as data); caps per call and per conversation; `MOMENTUM_LLM_SUPPORTS_VISION=false` gives `not_supported`. The mock transport reads image parts (text match, `[image WxH]` in request keys, `(w*h)/750` tokens) and treats the images message as the same turn. **Chat:** `ScreenIn.file_ids` (up to 5); each question's chips are stored on its user message and carried by later questions; the system block lists the conversation's files; `POST /ai/conversation-files` and `GET /ai/conversations/{id}/files`. **Citations:** `[F:<file> · <locator>]`, resolved as the reader (`references.py`; a chat-only file in `ai/citations.py`). **Prompts:** `chat/v2`, `command/v3`. **Web:** file chips and the paperclip in Ask Mo (`useMoFiles`), drag a file row into the composer, "Ask Mo about this file" from the Files tab and the task pane, file citation chips, file tool words in the activity line. **Evals:** features `file_qa` (13 mock + 6 live-only), `file_tables` (11 + 5), `file_vision` (10 + 5), `file_injection` (11 + 5) on the new eval workspace `onboarding_v1.yaml` (S75-03 stub: Northwind onboarding with every sample file, and a private Zenith project), all mock cases at 1.0; scorers `cites_locator`, `numbers_from_tools`, `query_exact`, `images_sent`, `answer_contains_number`, `no_leak`; the harness records each tool call's arguments and output (`RecordingRegistry`). **Tests:** `test_ai_files.py` (8: every tool refuses a private file for a non-member and a guest, tables and text through the tools, image caps and vision off, the images message and mock keys, hostile files propose nothing, notes become `create_task` previews only, chat files private and deleted with the chat, file citations as the reader), web `askFiles.test.tsx` (3), **J15 part 2** (e2e).

**S75-04 as built (2026-10-06).** Migration **0043** (`0043_s75_lifecycle.py`) holds every lifecycle table at once (decision D75-5): `field_defs.applies_to`, `projects.template_id`, `project_field_values`, `project_field_events`, the portfolio v2 columns, `portfolio_views`, `portfolio_members`, `project_snapshots` (the S75-05 parts are created here and used from S75-05). **Service** `domain/fields/project_values.py`: `list_project_field_defs`, `create_project_field`, `patch_project_field`, `project_field_values`, `field_history`, `set_project_field_value` (project editor; activity `project.field_set` with undo `projects.field_set`; one `project_field_events` row; event `project.field_changed` on `project:<id>` and every containing portfolio, found by `domain/portfolios/membership.portfolio_ids_containing`, manual or rule). Undo is a change too: it writes its own history row. **Templates:** "Save as template" stores `project_field_defaults`; "new from template" applies them and sets `template_id`. **Rules:** action `set_project_field` (`{field_id, value}`, the rule's own project only; validated against the field), engine `set_project_field_action` asks `domain/portfolios/gates.blocking_gate` first and never overrides a gate (D75-25, D75-26); conditions `title` and `type` (D75-24). **Mo:** tool `set_project_field` (risk low) and `get_project` lists project fields; `nl_rule/v6` with mock fixtures and eval cases (2 mock at 1.0, 2 live-only). **Web:** the Overview's **Details** card, "Applies to: Tasks / Projects" in the Fields dialog, "Set a field of this project" in the rule builder (with the field's own value editor) and the title/type conditions; MSW handlers for the new routes. **Found and fixed:** the rule sentence read "a custom field" for title/type conditions (caught by the new test); the projects ↔ templates foreign-key cycle broke the export/import table order (D75-27). **Tests:** `test_project_fields.py` (11: definitions apart from task fields, guests, every type with one history row and one activity each, history + events + undo (incl. the conflict), clearing, permissions, template defaults and lineage, the rule action with history and undo, rule validation, the gate skip and then the move once the gate is met, the Mo tool), `test_ai_tools.py` risk table and schema snapshot, web `overview.test.tsx` (+2), `ruleMeta.test.ts` (+1), `FieldsDialog.test.tsx` (+1). AC: the UI/API, rule and Mo paths each write exactly one history row and one undoable activity (asserted per path).

**S75-05 as built (2026-10-06).** No migration (0043 had every table). **Rows** (`domain/portfolios/rows.py`, `portfolio_rows_v2`): members by `membership.members_clause` (manual items or the rule) and the viewer's visibility; every built-in column of spec §5.3 plus `field:<id>` values, one SQL query per column family (13 whatever the size; the test asserts the count is the same for 1 and 40 projects; 40 projects took ~30 ms locally, budget 300 ms); filters (`q`, `status`, `owner_ids`, `stage`, project-field conditions, `overdue_only`), grouping (`status`, `owner`, `stage`, `field:<id>`) with rollups (count, average progress, overdue total, sums and averages of number/currency/percent fields), multi-key sort. **Lifecycle** (`domain/portfolios/lifecycle.py`): settings (rule, stage field, targets, gates, columns; validated against the project fields; undoable), manual ↔ rule (undoable), saved views (personal or shared; activity + undo), members (owner/admin manage; undoable), readiness (`gates.readiness`) and stage moves with the gate override. **Permissions:** `service.role_of` / `require_edit` (owner, admin, editor member); guests see a portfolio only as members (list, detail, rows, realtime subscribe). **Workload:** `project_ids` in the service, `portfolio_id` in the API. **Snapshots** (`domain/projects/snapshots.py`): `snapshot_all` (nightly job `snapshot_projects` 02:45, maintenance queue; same-day re-run replaces; 730-day retention), `backfill` (CLI `momentum snapshots backfill --days N`, plus `momentum snapshots today`). **API:** `GET /portfolios/{id}/rows`, `PATCH /portfolios/{id}/settings`, `POST /portfolios/{id}/convert`, views CRUD `/portfolios/{id}/views[/{view_id}]`, members `GET /portfolios/{id}/members`, `PUT`/`DELETE /portfolios/{id}/members/{user_id}`, `GET /portfolios/{id}/projects/{pid}/readiness?to=`, `POST /portfolios/{id}/projects/{pid}/stage`, `GET /workload?portfolio_id=`; `PortfolioOut` gains `kind`, `rule`, stage settings, `columns`, `my_role`. Existing endpoints and tests unchanged. **Found and fixed:** `GroupOut` clashed with the dashboards schema in OpenAPI (renamed `PortfolioGroupOut`); the sort parameter split `field:<id>:desc` at the first colon. **Tests:** `test_portfolio_v2.py` (10: every column incl. blocked, waiting on customer (and its configured choice), next milestone, stage age, target, forecast, slip; constant query count and timing for 40 projects; filters, grouping with rollups, sort; rule membership as the viewer with hidden counts; conversion both ways with undo; settings validation and undo; views personal and shared; members and guests; readiness and board moves with override and undo; workload by portfolio), `test_snapshots.py` (2), `test_portfolio_permission_matrix` (7 kinds of people × 6 actions).

**S75-06 as built (2026-10-06).** `momentum/seed_onboarding.py`, CLI `momentum seed --onboarding`. **Template** "Customer onboarding" (payload built directly, decision D75-36): sections Pre-sales, Discovery, Contracts, Implementation, Go-live, Hypercare, RAID; 36 tasks with the six milestones, seven roles (Sales AE, Discovery consultant, Contracts manager, Implementation lead, two consultants, Go-live and support); task fields Waiting on, RAID type, Severity (RAID tasks pre-filled); project field default Stage = Pre-sales; five rules `task.completed` + `title eq <milestone>` → `set_project_field` Stage. Project fields Stage (9 stages), Account owner, Contract value (EUR), Region, Target go-live, Products. Personas Sofia Reyes and Dev Patel, team **Customer Success**. **Customers:** `plan_customers()` is pure and deterministic (`random.Random(75)`): 40 synthetic companies in exactly the spec's stage counts, a stage path with durations around the targets (about 20 % breaches) fitted inside six months, some slipping, waiting-on-customer counts. Each customer is made from the template as Ravi, with its fields, its stage walk (one history row per stage, backdated to when it entered), the work of passed stages done (dates backdated), part of the current stage done, the current work overdue when slipping, waiting-on-customer tasks, files per stage from the sample builders (kickoff deck, SOW, quote, a signed contract from Implementation on, sometimes a screenshot), a comment and a status update; then real forecasts, a 180-day snapshot backfill and `ANALYZE`. Every gate holds for every customer past it (tested). **Portfolio** "Customer onboarding": rule `template_ids` + `include_completed`, stage field, the spec's targets and gates, the default columns, Ravi and Sofia as editors. **Eval workspace:** `onboarding_v1.yaml` adds `onboarding: {backfill_days: 30, quiet: [lena]}`, 12 customers from the same generator beside the S75-03 files and the hostile file. **Measured:** the seed takes ~85 s, a re-run ~1 s and adds nothing; on a fresh database right after the seed the portfolio's rows (40 projects, grouped by stage) take 30–60 ms (budget 300 ms). **Found and fixed:** templates dropped task types (milestones became tasks); `--onboarding` from the CLI needed every model registered (`import momentum.models`); stale planner statistics right after the seed (~4 s rows) fixed with `ANALYZE`. **Tests:** `test_seed_onboarding.py` (3: the plan is deterministic, in the stage counts and inside six months; the seeded demo (template, milestones, rules, portfolio board counts per stage in order, every gate consistent, lineage, history window, waiting-on-customer, stage age, snapshots, re-run adds nothing); the template's rule on a fresh project is held by the Implementation gate, then moves the stage once the gate is met).

**S75-07 as built (2026-10-06).** **Backend additions:** rows carry `can_edit` (`access.project_roles`, batched); `POST /portfolios/{id}/bulk-set-field` (one batch undo); `GET /portfolios/{id}/export/csv` (view params; formula guard reused from the project export); `GET /portfolios?summaries=true` (per-stage counts and total value); `momentum seed --onboarding --small`. **Web** (`features/portfolios/`): `v2queries.ts`, `cells.tsx`, `PortfolioTable.tsx` (saved views personal/shared, Save view / update / delete, group by with rollup rows, server sort from the headers, column picker (editors save), resizable columns (pointer and ←/→), inline project-field edits, bulk "Set field…", CSV export), `PortfolioBoard.tsx` (stage columns with count, value and target; cards with health, owner, value, days in stage, next milestone; pointer drag and a "Move to stage…" menu; the gate dialog with the checklist and Move anyway), `PortfolioTimeline.tsx` (bars, forecast cone, milestones, today, group by stage/owner, month/quarter), the Workload tab (`WorkloadPage portfolioId`), `PortfolioSettingsDialog.tsx` (by hand / by a rule with templates, teams, project field conditions, completed/archived; stage field, targets and gates per stage; members), list cards with stage mini-bars and the total value. MSW mock `mocks/portfolios.ts`. **Found and fixed:** Chromium exposes `th scope="rowgroup"` as a cell (now `scope="row"`); a list holding groups holding list items failed axe (now one list per group in a region); the board and table selects had no focus ring (keyboard pass). **Tests:** API `test_portfolio_v2.py` +3 (bulk set and its batch undo, CSV, summaries, `can_edit`); web `portfolioV2.test.tsx` (9: table columns, sort, group rollups, inline edit, bulk set, views and CSV link; board menu move and gate dialog with Move anyway, no stage field; timeline bars; workload scoped; settings stages and gates; list stage bars), `portfolios.test.tsx` on the Overview tab; **J16** green; **J14** adds the portfolio table, board and timeline and a project's Files tab to axe in both themes, and a keyboard-only board move. Full e2e 21/21. **UI audit** (`tools/ux/audit.mjs`, the new screens at every viewport): 308 screens, 0 findings; **keyboard pass**: 0 findings.

**S75-08 as built (2026-10-06).** Migration **0044** (`0044_s75_dashboards_v2.py`): `dashboards.filters` / `portfolio_id` (one live dashboard per portfolio) / `template`, the new widget kinds, `dashboard_members`, `dashboard_pins`, `user_visits` (for S75-11); the model now also declares 0043's `ix_projects_template` (the drift check is clean). **Query spec v2** (`domain/dashboards/schemas_v2.py`; v1 moved to `spec.py`, re-exported, decision D75-46): `TasksSpec` (v1 plus `portfolio_id`, `project_fields`, `split_by`), `ProjectsSpec` (filters incl. `slipping`, `has_blocked`, `has_waiting_on_customer`, `at_risk`, `assignee`; group by project field / owner / status / team / stage; six measures; time by created / a date field / stage entered; table columns; timeline), `StageSpec` (`funnel`, `time_in_stage`, `throughput`, `aging`), `SnapshotSpec`, `NoteSpec`; shared `compare_previous`, `target`, `period`; `check_any` per kind. **Engine:** `query_v2.run_any` / `drill_any` / `check_any` with the dashboard filters (D75-49); `query_scope.py` (visible projects, portfolio membership, "me", calendar periods), `query_tasks.py` (D75-47), `query_projects.py` (the portfolio's own `compute_rows`, extracted from `portfolios/rows.py`, so a dashboard and the portfolio table always agree), `query_stages.py` (stays from `project_field_events`), `query_snapshots.py`. **Service and API:** widgets store v1 or v2 (`AnySpec`), checked on every write; `GET /dashboards/widgets/{id}/data?filters=` (view filters; cached 60 s on the app, D75-50); `PATCH /dashboards/{id}` saves `filters`; `POST /dashboards/drill` takes any spec (projects and stages return `projects`), `split_key` for a stacked segment; members (`GET/PUT/DELETE /dashboards/{id}/members[/{user_id}]`, undoable, event `dashboard.member_changed`); pins (`GET /dashboards/pinned`, `PUT`/`DELETE /dashboards/{id}/pin`); the portfolio tab (`GET /dashboards/portfolio/{id}`, `POST /dashboards` with `portfolio_id`); **role templates** (`domain/dashboards/templates/*.yaml`, the seven of this slice's list; `role_templates.py` binds names, D75-52; `GET /dashboards/templates`, `POST /dashboards/from-template/preview`, `POST /dashboards/from-template`). The seed makes and pins each persona's dashboard (D75-53). **Web** (`features/dashboards/`): renderers for `kpi` (delta, target ring), `stacked_bar`, `table` (projects or tasks), `funnel`, `stage_time`, `aging`, `timeline`, `note` (`widgets2.tsx`); the editor's "What it shows" (Tasks, Projects, Lifecycle, Note; `WidgetEditorV2.tsx`); the filter bar (`FilterBar.tsx`, view for me in the URL, Save for everyone); the template gallery with the bound preview and its notes; Pin to Home and Home's "Pinned dashboards"; the portfolio **Dashboard** tab (last tab; from a template or blank); the drill lists projects for project and stage widgets. **Measured** (`tools/perf/dashboard_perf.py`, the 40-customer onboarding seed, a 10-widget dashboard (Leadership's eight plus the Control tower table and the RAID stacked bar) loaded as Ravi like the web app, six requests at a time, in-process, 30 loads): cold (cache cleared) p50 0.37 s, **p95 0.43 s**, max 0.54 s; warm p95 0.10 s (AC < 1.5 s p95); the slowest widget p95 0.24 s under that concurrency (budget 0.4 s). **Found and fixed:** `TemplateOut` clashed with the project templates' schema in OpenAPI (now `DashboardTemplateOut`); a calendar-period KPI compared with an equal-length window instead of the previous calendar period; a template widget bound on a portfolio without a stage field and failed only when read (binding now runs the checks); J16's `Board` tab locator also matched the new `Dashboard` tab. **Tests:** `test_stage_analytics.py` (5: known answers for the funnel with conversions, time in stage medians / p75 / p90 / targets and the KPI, throughput with the period before and its series, aging buckets and breaches, the stage drill and projects by stage), `test_dashboards_v2.py` (9: tasks v2 with a portfolio, table, stacked bar with segment drill and the previous calendar week; projects measures, table, timeline and drill; filters with "me" saved and for one view, with undo; members, pins and the portfolio tab; the cache; validation; template preview with dropped widgets and notes; every role template fills every widget for its persona on the onboarding seed; a KPI agrees with its table), every v1 test unchanged; web `dashboardsV2.test.tsx` (12: each new widget, the stage drill, filters view and save, pin, template preview); **J17** green (the PDF export step joins in S75-09); **J14** adds a role dashboard to axe in both themes. Full e2e 22/22. **UI audit** (adds the portfolio Dashboard tab and a role dashboard): 316 screens, 0 findings; **keyboard pass** (both added): 0 findings.

**S75-09 as built (2026-10-07).** Migration **0045** (`report_runs`, D75-55). **`momentum/reports/`:** `spec.py` (`ReportSpec`: kind, scope, period, format, sections, narrative, filters, audience; formats, sections and scopes per kind from spec §6.2; a customer status is always `audience=customer`), `document.py` (`ReportDocument` with Heading, Paragraph(ai, cites), KPIRow, Table (a `sheet` for xlsx data sheets), Chart, TaskList, Callout, PageBreak; the builder's `facts` and where the narrative goes), `data.py` (top-level tasks of visible projects with assignee, section and tags; task fields; "Waiting on = Customer"; blockers), `builders/` (`project.py`: project status, customer status, close-out, on the portfolio table's own `compute_rows`; `portfolio.py`: portfolio status on `portfolio_rows_v2`, the value column as the list page picks it; `tasks.py`: task export with custom fields and the dashboard engine's filters; `dashboard.py`: every widget through `run_any` with the saved filters), `render/` (`docx.py` python-docx with repeating table headers and Pillow chart pictures, `xlsx.py` openpyxl Summary sheet + data sheets with frozen headers, autofilter, widths, native charts and formula-safe text, `pdf.py` reportlab platypus with DejaVu Sans, header, footer and page numbers, vector charts, `text.py` Markdown and CSV with the S7.4 cell guard, `png.py`), `narrative.py` (the `Narrator` contract), `generate.py` (build → narrative → render; `outline` for the preview). **`domain/reports/`:** `service.py` (preview, request, execute (as the requester, in a savepoint, capped by `MOMENTUM_REPORT_TIMEOUT_S`, failures in words), regenerate), `runner.py` (the requester's context; run one queued run), `router.py` (`POST /reports/preview`, `POST /reports` (202), `GET /reports/jobs/{id}`, `POST /attachments/{id}/regenerate`), job `generate_report`. Attachments: `create_attachment` takes `verb` and `batch_id`; `GET /portfolios/{id}/files`; `AttachmentOut.generated_spec`. **AI:** `ai/report_narrative.py`, prompt `report_narrative/v1`, mock fixtures (and the mock's `{{$cites}}` slot), Mo tool `generate_report` (risk low; preview = outline). **Web:** `features/reports/` (`ReportDialog` with the live outline, the progress and ready toasts with Undo, `PortfolioReports`), "Create report" in the project menu, the portfolio header and the dashboard header, the portfolio **Reports** tab. **Tests:** `test_reports.py` (6: project status in docx, pdf and md with the KPIs equal to the portfolio rows, Unicode (Zoë Ångström — Привет ✓) in docx and pdf, the AI label in each format, one paragraph per part, no narrative when off; portfolio status xlsx (Summary KPIs equal the rows, the Projects data sheet frozen and filtered, the file listed on the portfolio) and docx; task export xlsx with a formula-looking title stored as text and the row count equal to the project's tasks, csv with the guard, filters narrowing it; customer status in docx and pdf without the `internal` task; close-out (planned vs actual, top blockers, the narrative) and the dashboard pdf with the widget's value, and a dashboard with no portfolio refused; preview outline and page estimate, wrong format refused, outsiders 404, the file in Files as a generated, AI-drafted report, regenerate as version 2, undo of both, someone else's job 404), `test_ai_reports.py` (3: the citation guard, facts as data with the `Citable:` line, `generate_report` preview → apply as the person → undo, outsiders and viewers refused), `test_ai_tools.py` (risk table and schema snapshot), evals `report_narrative` 10/10 mock; web `reports.test.tsx` (2); **J18** green; **J17** now exports the dashboard as a PDF that appears in the portfolio's Reports. Full e2e 23/23; **UI audit** (adds the portfolio Reports tab): 320 screens, 0 findings; **keyboard pass**: 0 findings. `test_undo_coverage` allow-lists `reports/service.py:execute` (its activity is recorded by `create_attachment`).

**S75-10 as built (2026-10-07).** No migration. **Read tools** (`ai/tools/portfolio_tools.py`, on `ai/portfolio_facts.py`): `get_portfolio_rows` (the table's rows, filters by health, stage names, owner, overdue, slipping, waiting on the customer; hidden projects counted) and `get_stage_metrics` (funnel, time in stage vs target, aging, the bottleneck). **Endpoints** (`ai/insight_router.py`, nothing stored): `POST /ai/portfolios/{id}/brief`, `POST /ai/filters`, `POST /ai/dashboards/draft`, `POST /ai/dashboards/widgets/{id}/explain`, `POST /ai/portfolios/{id}/projects/{pid}/readiness`, `POST /ai/projects/{id}/handoff`; plus `POST /dashboards/from-draft` (create the previewed dashboard, undoable). Project-field conditions gain `gte` / `lte` (D75-64). **AI:** `portfolio_brief.py`, `nl_filters.py`, `dashboard_draft.py` (recipes and `bind_template`, D75-63), `explain_chart.py`, `readiness_check.py`, `handoff.py`, `file_digest.py`, `grounding.py` (D75-65); prompts `portfolio_brief/v1`, `filters/v1`, `dashboard_draft/v1`, `explain_chart/v1`, `readiness/v1`, `handoff/v1`; mock fixtures for each; evals (mock, all at 1.0): `portfolio_brief` 10, `nl_filters` 13, `dashboard_draft` 12, `explain_chart` 11, `readiness` 10, `handoff` 10, plus 5 live-only each. **Web:** `features/portfolios/MoPortfolio.tsx` (Brief me in the header; Ask the portfolio above the table; "<Stage> readiness" in a board card's menu and Mo's file check in the gate dialog; the handoff offer after a move and its dialog), `features/dashboards/MoDashboards.tsx` (New with Mo on the Dashboards page; Explain in every saved widget's menu). **Found and fixed:** a JSON scalar's text needs `#>> '{}'` (the field value column has no `astext`); a sample file in the eval workspace carries an injection line, so the handoff-with-files case now checks that its uncited claim is dropped. **Tests:** `test_ai_portfolio.py` (6: the brief never names a hidden project, cites only visible ones, drops invented numbers, writes nothing until posted, and makes no call for someone who sees nothing; the read tools agree with the rows endpoint and hide what you can't see; filters resolve November and stages as the viewer, apply as the view's own schema and ask back with options; a dashboard draft previews four widgets with numbers, saves nothing, creates on post with the sentence on each widget, undoes, refuses a bad spec and asks for the portfolio; Explain cites its own data with task links and refuses a note; readiness reads files only when ticked and handoff is a preview until posted; outsiders 404), `test_ai_tools.py` (risk table, schema snapshot); web `moPortfolio.test.tsx` (3), `moDashboards.test.tsx` (2), and `dashboards.test.tsx`'s viewer case (Explain only).

**S75-11 as built (2026-10-07).** No migration (`user_visits` came with 0044). **Visits:** `domain/visits/` (`record_visit`, `last_seen`; `PUT /visits`, D75-70). **Catch me up:** `ai/catch_up.py` (since = asked / last visit / 7 days, capped at 30; other people's visible activity grouped and counted, at most 150 events; no model call when nothing changed, D75-71), prompt `catch_up/v1` (alias `fast`), `POST /ai/catch-up`, `GET /ai/catch-up/pending`. **Plain-English filters:** `ai/nl_filters_tasks.py` (list / board / calendar, My Tasks, search; field conditions through the chart's resolution; asked back when unsupported, D75-72), `FieldCondDraft.contains`, prompt `filters/v2`, `POST /ai/filters` takes `project_id`. **Web:** `features/ai/CatchUp.tsx` (`useVisitBeacon` on Home, projects and portfolios; `CatchUpButton` in the project and portfolio headers; `WhileYouWereAway` on Home; the dialog), ⌘K "Catch me up" and "Catch me up on <project>"; `features/ai/AskFilters.tsx` in the list / board / calendar toolbar, My Tasks, Search and (refactored onto it) the portfolio table. **Evals (mock, 1.0):** `catch_up` 12 (nothing changed → no call; own changes aren't news; completed, reassigned, due, mention, new + status, private work never shows, Home, a portfolio stage change, another viewer; invented and uncited lines dropped) + 5 live; `nl_filters` 25 (13 portfolio, 12 task surfaces) + 7 live. **Tests:** `test_ai_catch_up.py` (4: visits debounced and checked; what others changed since my visit with no call when nothing did, my own changes not news, the mention, counts and cited lines with task links, outsiders refused; private work never shows and the window is capped at 30 days, 7 with no visit; the Home card past 3 changes), `test_ai_filters.py` (4: a list draft is the view's preferences (and saves as is), board sort and group, a project view needs its project; unresolvable tags and unsupported words / due asked back with options, a hidden project never named; the search params; relative dates in the viewer's timezone at 23:30 UTC on 31 October); web `catchUp.test.tsx` (2), `askFilters.test.tsx` (2), the portfolio tests on the shared component; **J19** parts 1–2 (Home's "While you were away" after Ana finishes four tasks, the project's Catch me up, then "only my overdue work" → chips → Apply → marker → Clear).

## The prompt for the build session

Paste this into the browser session (also correct for resuming after a context reset):

> You are building **Phase 7.5** of Momentum. Read `CLAUDE.md`, then `docs/progress/STATUS.md`, then `docs/roadmap/phase-7.5.md` and the spec it links (`docs/superpowers/specs/2026-10-06-phase-7-5-ai-files-insight-design.md`) in full before writing code. Work through the slices in `phase-7.5.md` in order, starting from the first one STATUS doesn't mark done, until the Phase 7.5 exit is complete, without stopping to ask: every product decision is already made in the spec (D1–D8) and the phase file, and anything not covered is yours to decide by the spec's principles and record in STATUS under "Decisions (Phase 7.5, delegated)". There is **no AI gateway** in this environment: use `MOMENTUM_LLM_MODE=mock` for everything; every AI feature needs handwritten mock fixtures and mock eval cases at 1.0, and live-only cases written for later. Follow the "Working rules for the build session" in `phase-7.5.md` exactly: the full gate green per slice, docs in the same slice, one commit per slice (`Phase 7.5 S75-NN: …` with the Co-Authored-By line), `git fetch` + rebase and push to `main` after each green slice (never force-push, never push red), and update STATUS (checkbox, date, result, next up, handoff) after every slice so a new session can resume from it. Finish by completing S75-13 (exit table, live verification checklist, INTEGRATION_GUIDE change log) and reporting what was built, the gate results and anything deferred.
