# AI Development Workflow

How the human (product owner, reviewer, and committer) and the AI (implementer) build Momentum together.

## 1. Roles

| Human | AI |
|---|---|
| Sets priorities, approves phase plans, answers questions | Proposes plans, implements slices, writes tests and docs |
| Runs the app, tries features, gives feedback | Reports how to try each slice, fixes feedback |
| Commits and pushes | Proposes commit messages; never assumes a push happened |
| Approves ADRs and risky changes | Writes ADR drafts; stops and asks at the §6 triggers in CLAUDE.md |

## 2. Rolling-wave planning

- The **roadmap** (`roadmap/roadmap.md`) fixes phases and their order.
- Each **phase file** lists epics and slices with acceptance criteria.
- **Phase kickoff** (start of every phase): the AI re-reads the phase file against the current code and the lessons in STATUS, then proposes refinements (split/merge slices, update ACs, note risks) using `templates/phase-kickoff.md`. The human approves. This keeps later phases accurate without over-planning now.
- **Phase exit:** all slices done, the E2E journeys for the phase pass, the STATUS retro is written, and the demo is done.

## 3. Slice lifecycle

```
┌ 1. Pick ─ STATUS "Next up" → the slice in phase-N.md
├ 2. Restate ─ goal, ACs, out-of-scope, files to touch, questions  → (human OK if questions)
├ 3. Build ─ migration → model → schema → service → router → tools → web api/queries → UI
├ 4. Test ─ per testing-strategy §3; make check green
├ 5. Docs ─ per CLAUDE.md §5 (STATUS always)
├ 6. Report ─ summary · how to try · screenshots/notes · deferred items · commit message
└ 7. Feedback loop ─ human tries it → fixes → human commits & pushes → STATUS marks done
```

**Slice size guard:** if a slice grows past ~600 changed lines (excluding generated files and tests) or takes more than one working session, split it and record the split in the phase file.

## 4. Session handoff (context continuity)

AI sessions have limited memory, so the repository carries the context:

- `docs/progress/STATUS.md` → **Current focus** and **Handoff notes** sections are updated at the end of every session, even mid-slice: what's done, what's half-done (file list), next steps, gotchas.
- WIP rule: never leave `make check` red at the end of a session without a handoff note explaining why and how to fix it.
- Long-lived knowledge (patterns, gotchas) moves from handoff notes into the right doc (coding standards, architecture) at phase exit.

## 5. Asking questions

Batch questions at the **Restate** step. Each question offers options with a recommendation, so the human can answer quickly: *"Q1: Should completed subtasks be hidden in the list view? (a) hidden with a count (recommended) (b) shown struck through."*

## 6. Slice report template

```markdown
## S1.2.3 Inline assignee & due date: done

**What changed**
- API: PATCH /tasks/{id} supports assignee_id, due_on, due_at; NL date parsing on client
- UI: AssigneePicker, DatePicker (NL input), keyboard A/M/D
- Tests: 14 new (service 6, api 4, web 4); make check ✅

**Try it**
1. make dev → log in as "Ravi (dev)"
2. Open "Website Revamp" → focus a task → press D → type "next fri" → Enter

**Docs updated:** STATUS, ux-specs §4.2 (shortcut clarification)
**Deferred:** time-of-day due (S2.x). Recorded in phase-2 backlog
**Deps added:** chrono-node (NL date parsing, MIT)

**Suggested commit**
S1.2.3: inline assignee and due date editing
- Assignee/Date pickers with keyboard shortcuts (A, M, D)
- NL date parsing ("tomorrow", "next fri") with timezone awareness
- Activity + undo for assignee/date changes
```

## 7. Documentation hygiene

- Docs describe intent; OpenAPI and code describe the implementation. Don't duplicate endpoint lists in docs beyond the phase file notes.
- When the implementation deliberately deviates from a doc, update the doc in the same slice and add a line to STATUS → "Plan changes".
- ADR for decisions that are hard to reverse (datastore, auth, protocol, library with deep reach).

## 8. Definition of Done (global)

- [ ] Acceptance criteria met and demonstrated
- [ ] Tests per testing-strategy §3; `make check` green
- [ ] Loading/empty/error states handled (UI slices)
- [ ] Activity + outbox + undo for mutations
- [ ] AI tool registered for new mutations (from Phase 3 on; before that, noted in the Phase 3 backlog)
- [ ] Docs updated (CLAUDE.md §5)
- [ ] No secrets, no real data, no raw colors, no model ids in code
- [ ] Slice report delivered
