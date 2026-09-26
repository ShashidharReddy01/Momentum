# Slice session procedure

How one AI session builds one slice, cheaply and to the same quality bar. It adds to `CLAUDE.md` and `ai-dev-workflow.md`; where they disagree, `CLAUDE.md` wins. The human starts each slice in a fresh session with a ~10-line prompt (format at the bottom); each session ends by printing the next one.

## 1. Orient (keep it cheap)
- Read `docs/progress/STATUS.md` (about 120 lines: Current focus, the latest handoff, open questions, progress, plan changes) and the slice's own section in `docs/roadmap/phase-N.md`. Read the phase's "Read first" docs and any doc the slice touches, but **Grep first; don't read whole files over ~300 lines**. Don't open `handoff-archive.md` unless the slice touches that area.
- Model check: compare with the table below and `model-guide.md`. If you know you're on a different model, say so in one line and carry on.
- `git status` clean and HEAD matches the prompt. Run ruff + mypy (fast). **Don't re-run the full test suites as a baseline**: the previous session's final gate was green at that HEAD; the full gate runs once, at the end.

## 2. Restate, then build
- Restate in at most 15 lines: goal, ACs, out of scope, files. Don't wait for an answer.
- **Ask only for the `CLAUDE.md` §6 triggers** (ambiguous or conflicting ACs, a new architectural dependency or ADR deviation, a migration that drops or rewrites data, anything touching auth, permission semantics or AI autonomy defaults). Otherwise pick the sensible default and record it under "Decisions" in the handoff. Batch any questions into one message with a recommendation each.
- Build in the `CLAUDE.md` §2 order (migration, model, schemas, service, router, AI tool registration, frontend API hooks, UI, tests). One write path, activity + outbox in the same transaction, permission checks in services, settings in `momentum.core.settings` + `docs/architecture/configuration.md` + `.env.example`.
- If the slice passes ~600 changed lines (excluding generated files and tests), split it, record the split in the phase file, and build the first part.

## 3. Test as you go
- Run **only the touched test files** while working (`uv run pytest -q tests/test_x.py`, `pnpm exec vitest run <path>`).
- Write tests for every AC. For each risky rule (permissions, loop protection, dedupe, public endpoints, anything security-shaped) **do a mutation check**: break the rule, see a test fail, restore it. Put one line per check in the handoff. A mutation that survives means a missing test: add it.
- **AI slices** (a new or changed prompt, tool or AI action): add eval cases in `momentum/ai/evals/cases/` (10+ per feature, structural expectations first; a judge rubric may only ask for what the feature can see). Live evals: one `EVALS_LIVE=1 uv run momentum evals --feature <f>` while iterating (repeat 3x if a case flaps), and **at most one full live run at the end**. Non-AI slices run no live evals.

## 4. Efficiency rules (these save tokens without lowering quality)
- Batch independent tool calls in one turn. Keep command output short (`tail`, `head`, `cut`, `grep -c`). Run anything over ~1 minute in the background and wait for the notification.
- Use the Edit tool for edits. If you script an edit, assert the target exists and keep LF line endings. Don't re-read a file you just edited. Don't spawn subagents unless the slice truly needs parallel work.
- Don't narrate; state decisions and results.

## 5. Final gate (once, at the end)
Backend (`apps/api`): `uv run ruff format --check momentum tests`, `uv run ruff check momentum tests`, `uv run mypy momentum`, `uv run lint-imports`, full `uv run pytest -q` (about 10-18 min: background). If you changed the API: regenerate types (`uv run python -m momentum.openapi_dump > ../../.openapi.json`, then `pnpm exec openapi-typescript ../../.openapi.json -o src/momentum/lib/api/schema.d.ts` in `apps/web`, then delete the json). If you added a migration: apply it and confirm no model/DB drift.
Web (`apps/web`): `pnpm exec prettier --check src e2e`, `pnpm exec tsc --noEmit`, `pnpm exec eslint .`, `pnpm exec vitest run` (about 17 min here: background).
E2E when the slice has a UI journey (its own `j*` file, or it touches a shell/list/pane journey): `MOMENTUM_E2E_CHROMIUM="C:\Program Files\Google\Chrome\Application\chrome.exe" pnpm exec playwright test`. For UI slices look at a screenshot of the result.
Everything must be green. Never end on red without a handoff note.

## 6. Docs, commit, push, next prompt
1. Docs per `CLAUDE.md` §5. `STATUS.md`: tick the slice, update Current focus and Next up, **replace the latest handoff with this session's (at most 25 lines: what shipped, Decisions, mutation checks, gotchas, how to try it, deferred) and move the previous handoff to `docs/progress/handoff-archive.md`**. Bump a prompt's `version` when you change its wording.
2. One commit: `S4.x.y: <title>` + a body + the attribution line from the session's system reminder. **Then `git push origin <current branch>`** (the product owner authorizes pushing this feature branch for slice work; never force-push, never push to `main`; if the push fails, say so and stop).
3. Final message, short: what changed, how to try it (exact clicks), what's deferred, verification numbers. Then the next prompt (below) in a fenced block.

## 7. Windows dev machine notes
- `make` isn't installed: run the steps above directly. Create `reports/evals` before redirecting into it.
- If Postgres is unreachable, Docker Desktop probably stopped: start it, then `docker start compose-postgres-1` (data persists; superuser is `momentum`).
- Tests that use dates must use the actor's timezone, not the machine's (`date.today()` breaks after local midnight).
- Live results vary run to run; a case that fails twice is a finding, not noise.
- Dollar cost is unmeasured until `MOMENTUM_LLM_PRICE_TABLE` is set (product-owner decision open).

## 8. Phase 4 slices and models
| Slice | Model | Extra |
|---|---|---|
| S4.1.1 Rule model and executor | Opus | loop protection proven with mutation checks |
| S4.1.2 Actions library | Sonnet | |
| S4.1.3 Rule builder UI and run history | Sonnet | screenshot check |
| S4.1.4 NL to rule | Opus | 20 phrase evals (>= 90% exact, the rest ask back), live run |
| S4.1.5 AI step action | Sonnet | AI evals |
| S4.2.1 Form builder (+ public forms) | Sonnet | then a security review pass of the public endpoint (spam limits, no auth leakage, input handling) |
| S4.2.2 Conversational intake | Sonnet | AI evals |
| S4.3.1 Project templates | Sonnet | |
| S4.3.2 Task templates | Sonnet | |
| S4.3.3 Template from description (AI) | Sonnet | AI evals |
| S4.4.1 Approvals | Sonnet | agents can't decide |
| S4.4.2 Recurring tasks | Sonnet | NL input |
| **Phase 4 exit** | Sonnet | J9 (mock e2e); loop protection proven; 20 NL rule phrases pass live; form, triage and assignment flow works end to end; full live evals; retro in STATUS; `INTEGRATION_GUIDE.md` change log; then the next phase's kickoff prompt |

Escalate to Opus per `model-guide.md` §3 (red twice on the same problem, > ~600 lines or a design change, an unexplainable bug, generic-looking UI).

## 9. The next-slice prompt (print exactly this shape, filled in)
```
Phase 4, slice S4.x.y: <title>. Model: <Sonnet|Opus>.
Follow docs/process/slice-session.md exactly (it says how to orient, build, test, gate, document, commit, push, and print the next prompt).
Repo: branch claude/clever-hopper-pbv7yr, HEAD <short hash>, tree clean.
Carry-over (only what the git history and STATUS don't already say):
- <3-8 bullets: new tables/modules/events this slice added that the next one uses, decisions that constrain it, gotchas>
```
For the last slice, the next prompt is the Phase 4 exit; after the exit, it is the next phase's kickoff (`docs/roadmap/phase-N-kickoff.md` pattern, as Phase 3 did).
