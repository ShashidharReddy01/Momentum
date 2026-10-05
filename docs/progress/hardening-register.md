# Hardening register (Phase 7)

Every finding from the Phase 7 audit (E7.0) and the Phase 6.5 exit (UX8), one row each. **Policy (product owner, 2026-10-04): every finding is fixed, P3 included**; the AI triages and records decisions here.

Severity: **P0** broken, data loss, security or permission leak · **P1** wrong, confusing, or a crash on reachable input · **P2** polish · **P3** nice-to-have.
Status: open → fixed (commit) · each fix ships with the test that proves it.

How findings are found:
- **Robustness sweep** (`apps/api/tests/test_api_robustness.py`): every API operation with boundary values (NUL, emoji/RTL, 10k characters; `PROBE_FULL=1` adds wrong types and extreme numbers); any 5xx is a finding.
- **UI audit** (`tools/ux/audit.mjs` on `tools/ux/serve.sh`): every screen at 5 viewports × 2 themes: page overflow, clipped / covered / unnamed controls, axe WCAG 2.2 AA serious+critical, console errors; screenshots reviewed by eye.
- **Edge-case review** per feature (the matrix in `phase-7.md` E7.0), **live AI runs** against the real gateway, and the **150-user load test**.

| # | Sev | Area | Finding | Found by | Status |
|---|---|---|---|---|---|
| H1 | P1 | API (all text input) | A NUL character (`\u0000`, which text pasted from PDFs or Word can carry) in any text field, search box or query parameter made the API fail with a 500: Postgres rejects NUL in text and JSON. 25+ operations (users, teams, tasks, tags, portfolios, goals, dashboards, search, mentions, templates, agents, Mo chat, AI memory, the Asana import). | Robustness sweep | fixed: `StripNulMiddleware` (`core/http.py`) removes NUL from API query strings and JSON bodies; `core/text.strip_nul` for other boundaries; sweep green |
| H2 | P1 | Asana import | A personal access token with a non-ASCII character crashed the import (500) while building the HTTP header, instead of saying the token is invalid. | Robustness sweep | fixed: the token must be printable ASCII (422 otherwise) |
| H3 | P1 | Asana import | `team_name` longer than 120 characters crashed the import (500, varchar overflow) instead of a 422. | Robustness sweep | fixed: `team_name` 1–120 characters; Asana ids a safe token pattern |
| H4 | P2 | Home | The onboarding strip uses a sparkle icon, which reads as AI (amber ✦ is reserved for AI) on a non-AI checklist (Phase 6.5 audit #9, still open). | UI audit (screenshot) | open |
| H5 | P2 | Home | Recent-project tiles show a large letter avatar that repeats the project name (Phase 6.5 audit #9, still open). | UI audit (screenshot) | open |
| H6 | P1 | Web performance | Initial JS was 334 KB gzip, over the 300 KB budget (Phase 6.5 exit criterion): every screen loaded eagerly, and feature barrels defeated code splitting. | UX8 bundle check | fixed: 291 KB. Secondary screens, project tabs, project menu dialogs and shell overlays load lazily (from their own modules, not feature barrels); app modules declared side-effect free; English-only date parsing; `tools/perf/bundle-budget.mjs` checks it |
| H7 | P2 | Shell | The notification badge sits over the bell's centre, so clicking the number can miss the button. | UI audit (covered control, 184 screens) | fixed: the badge lets clicks through |
| H8 | P1 | Accessibility | Avatar initials (light text on the person's colour) fail WCAG AA contrast everywhere avatars appear. | UI audit (axe color-contrast) | fixed: avatars are a tint of the person's colour with deep text of the same hue (min 5.7:1 light, 5.5:1 dark) |
| H9 | P1 | Accessibility | `text-muted-2` is used for real text (inbox times and kinds, search meta, calendar dates in dark, My Tasks/Home/Workload labels in dark) and fails AA contrast. | UI audit (axe color-contrast) | fixed: `--muted-2` is #5c6672 light (≥5.0:1 on every surface) and equals `--muted` in dark |
| H10 | P2 | Accessibility | Task lists (project sections, My Tasks buckets) declare a list role whose children aren't list items (virtualised wrappers, empty sections). | UI audit (axe aria-required-children) | fixed: the section / bucket footer (Add task, drop zone) is a list item |
| H11 | P2 | Accessibility | Calendar day cells carry a cell role without a row parent. | UI audit (axe aria-required-parent) | fixed: the month is a `grid` with a header row and a row per week |
| H12 | P2 | Accessibility | The "New comment" editor wrapper has an `aria-label` on a role-less div (prohibited). | UI audit (axe aria-prohibited-attr) | fixed: the comment editor is a labelled `textbox` |
| H13 | P2 | Accessibility | Search's project / assignee / completed filters are unlabelled selects. | UI audit (axe select-name) | fixed: the filters are labelled |
| H14 | P2 | Members | A non-admin opening Settings → Members gets a blank page (and a 403 behind it); at 150 people everyone should at least see a read-only directory. | UI audit (screenshot + console) | fixed: non-admins see the active-member directory with a count; admins keep the full roster |
| H15 | P1 | Task pane | With a task open at 1024–1440 px the pane takes ~560 px: list titles shrink to ~10 characters, and at 1024 px the subtask count overlaps the avatar and date. | UI audit (screenshots, covered controls) | fixed: the pane defaults to 38% of the window (400–640 px), can be dragged or resized from the keyboard, and remembers its width; list titles clip inside their own cell; narrow lists show only the due date, not the range |
| H16 | P2 | Task pane | A large empty gap between the "Description" heading and the description text. | UI audit (screenshot) | fixed: the formatting toolbar shows below the text, only while editing |
| H17 | P2 | Board | "Add card" sits at the bottom of each column, far from the last card; an overflowing board gives no sign that more columns exist; an empty column has no hint. | UI audit (screenshot) | open |
| H18 | P2 | Timeline | Bar labels run into dependency arrows (Phase 6.5 audit #17, still open). | UI audit (screenshot) | open |
| H19 | P2 | Inbox | Notification rows repeat their kind ("Approval requested · Approval requested: …", "Overdue · … is overdue"). | UI audit (screenshot) | open |
| H20 | P2 | Overview | The Status card shows only the status chip; the latest update's title, summary, author and date are missing although the project has updates. | UI audit (screenshot) | open |
| H21 | P2 | Goals | Sub-goal periods print raw ISO dates ("2026-09-20 – 2026-12-03") (Phase 6.5 audit #17, still open). | UI audit (screenshot) | open |
| H22 | P2 | Agents | Schedules show raw cron ("Schedule (0 15 * * FRI)") instead of words ("Fridays at 3:00 pm"). | UI audit (screenshot) | open |
| H23 | P2 | Calendar | Every day cell shows a tinted drop bar even when nothing is being dragged, which makes the month noisy. | UI audit (screenshot) | open |
| H24 | P3 | Settings | `/settings` is "Not found": there is no settings home listing Profile, Notifications, Members, AI, API tokens and Import. | UI audit (screenshot) | open |
| H25 | P3 | Phone | At 390 px the project title wraps to three lines and the view tabs run off the edge with no scroll cue. | UI audit (screenshot) | open |
| H26 | P3 | List | Number custom-field values show as bare numbers ("8", "13") with no field name or unit. | UI audit (screenshot) | open |
| H27 | P2 | List | A section whose tasks are all completed shows only "Add task", no "N completed" hint (Phase 6.5 audit #15, still open). | UI audit (screenshot) | open |
| H28 | P2 | Scale | People pickers and the members directory listed at most 200 people unfiltered: a hard ceiling not far above the planned ~150. | Code review (H14) | fixed: up to 1,000 (API and pickers) |
| H29 | P2 | Test infrastructure | The robustness sweep runs as admin and as a member; it now builds 17+ entity kinds so handlers past their 404 get exercised. | Robustness sweep | fixed |
