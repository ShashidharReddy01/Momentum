# Model Guide: When to Use Opus 5.5 vs Sonnet 5

**Default: Sonnet 5.** The specs, conventions, and `make check` carry most of the difficulty, so Sonnet 5 builds the majority of slices well, faster and cheaper.
**Opus 5.5** is for work where judgment matters more than following a spec.

## 1. How to use this guide

1. At the start of a session, look at **STATUS.md → Current focus → Model**. It names the model for the next slice.
2. The AI also checks this table at session start (CLAUDE.md §1). If you're on a different model than recommended, it says so in one line before starting, e.g., *"Next slice S1.2.4 is tagged Opus; you're on Sonnet. Switch, or continue?"* You decide; it's advice, not a block.
3. Switching mid-phase is safe. Context lives in `STATUS.md` (handoff notes) and the docs, not in the chat.

## 2. Always Opus

- **Whole phases on Opus (product owner decision, 2026-09-23): Phase 1, Phase 3, Phase 5.** The per-slice tags below still apply to the other phases.

- **Phase kickoff** (the start of every phase) and **phase exit review** (retro, doc updates, integration-guide changelog).
- Any change to **auth, permissions, or AI safety/autonomy rules** (CLAUDE.md §6 areas).
- **Destructive or data-rewriting migrations.**

## 3. Escalate from Sonnet to Opus when

- `make check` fails twice on the same problem, or a fix causes a new failure elsewhere.
- The slice grows past ~600 changed lines, or the design has to change from what the phase file says.
- A bug can't be reproduced or explained after one attempt (race conditions, realtime ordering, flaky tests).
- The UI result looks wrong or generic in screenshots and needs design judgment.

After Opus unblocks it, switch back to Sonnet for the rest of the phase.

## 4. Slice-by-slice recommendation

**O** = Opus 5.5, **S** = Sonnet 5. Kickoff and exit of every phase = **O**.

### Phase 1: Core tasks (whole phase on Opus by decision; tags kept for reference)
| Slice | Model | Why |
|---|---|---|
| S1.1.1 Teams | S | Standard create/edit |
| S1.1.2 Projects | **O** | Project privacy and the visibility matrix are permission rules |
| S1.1.3 Project members and roles | S | Builds on S1.1.2's rules |
| S1.2.1 Sections | **O** | Ordering algorithm (fractional keys, concurrency) |
| S1.2.2 Tasks: create/edit/complete | **O** | Core list mechanics, task numbering under concurrency, optimistic UI |
| S1.2.3 Assignee and dates | S | Pickers + natural-language dates (spec is precise) |
| S1.2.4 Drag and drop, multi-select, bulk | **O** | Hardest UI slice: multi-drag, batch undo |
| S1.2.5 Filter, sort, group | S | |
| S1.2.6 List performance | **O** | Profiling and rendering judgment |
| S1.3.1 Task pane | **O** | Autosave, version conflicts, drafts |
| S1.3.2 Subtasks | S | |
| S1.3.3 Followers | S | |
| S1.4.1 Comments, mentions, reactions | S | |
| S1.4.2 Activity feed | S | |
| S1.4.3 Generic undo | **O** | Cross-cutting correctness |
| S1.5.1 My Tasks | S | |
| S1.5.2 Home | S | |

### Phase 2: Daily-use parity
| Slice | Model | Slice | Model |
|---|---|---|---|
| S2.1.1 WS hub + outbox dispatcher | **O** | S2.1.2 Frontend realtime client | **O** |
| S2.2.1 Board | S | S2.2.2 Calendar | S |
| S2.2.3 View switcher | S | S2.3.1 Field definitions | S |
| S2.3.2 Fields in views | S | S2.3.3 Tags | S |
| S2.4.1 Multi-homing | **O** (visibility rules) | S2.4.2 Dependencies | S |
| S2.4.3 Milestones | S | S2.5.1 Notification generation | S |
| S2.5.2 Inbox UI | S | S2.5.3 Notification prefs | S |
| S2.6.1 Attachments | S | S2.6.2 Global search | S |
| **S2.7.1 Asana importer** | **O** | S2.7.2 CSV import | S |
| S2.7.3 Onboarding | S | | |

### Phase 3: AI layer (Mo) (whole phase on Opus by decision)
| Slice | Model | Slice | Model |
|---|---|---|---|
| S3.1.1 LLM gateway + llm-check | S | S3.1.2 Tool registry + dry-run | **O** |
| S3.1.3 AI actions (preview/apply/undo) | **O** | S3.1.4 Embeddings + hybrid retrieval | **O** |
| S3.1.5 Workspace memory + context | S | S3.2.1 Smart quick-add | S |
| S3.2.2 ⌘K natural-language commands | **O** | S3.3.1 Ask Mo chat | **O** |
| S3.3.2 Contextual entry points | S | S3.4.1 Summaries | S |
| S3.4.2 Subtask breakdown | S | S3.4.3 Status draft | **O** (factuality) |
| S3.4.4 Writing help | S | S3.4.5 Plan my day | S |
| S3.4.6 Project from brief | **O** | S3.5.1 Eval harness | **O** |
| S3.5.2 AI usage admin | S | | |

### Phase 4: Workflow and intake
| Slice | Model | Slice | Model |
|---|---|---|---|
| S4.1.1 Rule executor + loop protection | **O** | S4.1.2 Actions library | S |
| S4.1.3 Rule builder UI | S | S4.1.4 Plain-English → rule | **O** |
| S4.1.5 AI step action | S | S4.2.1 Form builder (+ public forms) | S (Opus review of public endpoint) |
| S4.2.2 Conversational intake | S | S4.3.1–S4.3.3 Templates | S |
| S4.4.1 Approvals | S | S4.4.2 Recurring tasks | S |

### Phase 5: Agents (whole phase on Opus by decision)
| Slice | Model | Slice | Model |
|---|---|---|---|
| S5.1.1 Agent model + accounts | S | S5.1.2 Runtime loop + triggers | **O** |
| S5.1.3 Runs UI | S | S5.1.4 Autonomy, budgets, kill switches | **O** |
| S5.2.1–S5.2.3 Agents as teammates, gallery | S | S5.3.1 Daily Digest | S |
| S5.3.2 Triage | **O** | S5.3.3 Status Reporter | **O** |
| S5.3.4 Nudger | S | S5.3.5 Planner | **O** |
| S5.3.6 Meeting Notes | **O** | S5.3.7 Risk Watcher | **O** |
| S5.3.8 Generic teammate | S | | |

### Phase 6: Planning and insight
| Slice | Model | Slice | Model |
|---|---|---|---|
| S6.1.1 Timeline view | **O** | S6.1.2 Dependency-aware rescheduling | **O** |
| S6.2.1 Project overview | S | S6.2.2 Portfolios | S |
| S6.3.1–S6.3.2 Goals | S | S6.4.1 Workload view | S |
| S6.4.2 AI rebalancing | **O** | S6.5.1 Dashboards | S |
| S6.5.2 Ask for a chart | **O** | S6.5.3 Forecasting + risk score | **O** |

### Phase 7: Integrations
| Slice | Model | Slice | Model |
|---|---|---|---|
| S7.1 API tokens + MCP server | **O** (auth) | S7.2 Slack app | **O** (data exposure rules) |
| S7.3 Outlook calendar | S | S7.4 Email-to-task | S |
| S7.5 Outgoing webhooks | S | S7.6 Code-host (optional) | S |

### Phase 8: Hardening
| Slice | Model | Slice | Model |
|---|---|---|---|
| S8.1 PWA and mobile | S | S8.2 Performance pass | **O** |
| S8.3 Export / import | S | S8.4 Security review | **O** |
| S8.5 Accessibility | S | S8.6 Admin completeness | S |
| S8.7 Backup/restore rehearsal | S | | |

### Phase 9: Azure and go-live
| Slice | Model | Slice | Model |
|---|---|---|---|
| S9.1.1 Blob storage | S | S9.1.2 Telemetry | S |
| S9.1.3 Office LiteLLM check | S | S9.2.1 Bicep core | S |
| S9.2.2 Easy Auth config | **O** (auth) | S9.2.3 Networking | S |
| S9.3.1 CI/CD | S | S9.3.2 Runbooks | S |
| S9.3.3 Go-live | **O** (final verification) | | |

## 5. Rough split

About **35%** of slices are Opus and **65%** Sonnet, and the Opus share is concentrated in Phases 1 (list mechanics), 3 and 5 (AI), and 6 (timeline and forecasting). Revisit this table at each phase kickoff. If Sonnet handles tagged-Opus work well in practice, downgrade the tag and note it in STATUS.
