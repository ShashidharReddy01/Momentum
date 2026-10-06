# Edge-case matrix (Phase 7, E7.0)

For every feature built in Phases 0–6.5, which tests cover each edge case listed in `phase-7.md` E7.0. Findings are in `hardening-register.md` (H-numbers). Test files are under `apps/api/tests/` (backend), `apps/web/src/**` (web unit tests) and `apps/web/e2e/` (journeys J1–J14).

## 1. Sweeps that cover every feature

Several dimensions are checked by one test that walks the whole API or the whole UI, so a new endpoint or screen is covered without anyone remembering to add a case.

| Dimension | Sweep | What it enforces |
|---|---|---|
| Long and unicode text, bad input | `test_api_robustness.py` | Every API operation, with NUL, emoji / right-to-left text, 10,000 characters (`PROBE_FULL=1`: wrong types, extreme numbers): never a 5xx (H1–H3, H41) |
| Every role: anonymous | `test_security.py::test_every_api_route_refuses_an_anonymous_caller` | Every operation refuses a caller with no session, except a reviewed public list |
| Every role: project roles | `test_permission_matrix.py` | Admin, editor, commenter, viewer, outsider, assignee, collaborator × every task action on a private project |
| Every role: guest | `test_guests.py` | Only explicitly shared projects and their people (H61) |
| Every role: API token, agent | `test_api_tokens.py` (scopes, read-only guest tokens), `test_agents.py` / `test_agent_*` (`forbid_agent`, explicit-only access, no delete) | |
| Undo of every mutation | `test_undo_coverage.py` | Every recorded undo op has a handler; every Phase 1 mutation and tags, fields, rule / form delete and reactions round-trip exactly (H53–H57) |
| Every mutation leaves a trail | `test_undo_coverage.py::test_every_mutation_records_activity` | A service that emits an event without an activity row fails the build, except a reviewed list of system events (H55, H57) |
| Deleted or archived parents | `test_deleted_parents.py` | Section, parent task, task, project archive, disabled person: everything hanging off them answers 4xx, never 5xx; restored things are visible (H58, H59) |
| Huge | 150-user load test (`tools/load/`, ADR-0010, `performance.md`): 50,000 tasks, 75 concurrent, every endpoint class within budget; timeline 500 tasks (S6.1.1a); pickers up to 1,000 people (H28) | |
| Keyboard only | `tools/ux/keyboard.mjs` (every screen), J14 (list → pane → back), Phase 6.5 keyboard pass | H43, H44, H51 |
| Accessibility | J14 axe on 15 pages × 2 themes, `tools/ux/audit.mjs` (5 viewports × 2 themes) | H8–H13, H33, H34 |
| Realtime and reconnect | `test_realtime_hub.py::test_replay_delivers_backlog_in_order_on_reconnect`, `test_realtime.py` (channel access re-checked, H30), outbox ordering under concurrent writers (H39), web `realtime/client.test.ts` and the reconnecting banner | |
| Concurrency | `test_tasks.py::test_numbers_unique_under_concurrency`, `test_ordering.py::test_concurrent_inserts_*`, `test_identity.py::test_concurrent_first_requests_create_one_user_and_link`, version conflicts (below), `test_agent_runtime.py::test_two_workers_claiming_at_once_never_share_a_run` (H50) | Different fields never clobber each other; the same field is last-write-wins and live (reviewed, register) |

## 2. Per feature

"Sweep" means the row in §1 covers it. Cells name the feature's own tests for that dimension.

| Feature | Empty / huge | Two people at once | Deleted / archived parents | Time: timezone, DST, month ends | Undo | Notes |
|---|---|---|---|---|---|---|
| Tasks, subtasks | `test_subtasks.py`, load test | `test_rename_version_conflict_and_undo`, `test_numbers_unique_under_concurrency` | sweep; restore into a deleted section (H58) | `test_task_views.py` (due buckets in the person's timezone) | sweep | |
| Description | `test_task_description.py` (empty doc → none) | `test_save_and_conflicts_only_on_concurrent_description_edits` | sweep | | sweep | Keep mine / Use theirs |
| Sections, ordering | `test_sections.py` | `test_concurrent_inserts_keep_distinct_order` | sweep (delete with move / delete) | | sweep (`test_undo_move_conflicts_after_another_move`) | |
| Projects, teams, members | `test_projects.py`, `test_teams.py` | `test_rename_to_an_existing_name_conflicts` | archive / unarchive (sweep), last lead (`test_teams.py`) | | sweep | |
| Comments, mentions, reactions | `test_comments.py` | | sweep | | sweep (H57) | `test_mentions_follow_and_invisible_targets_are_dropped` |
| Followers | `test_followers.py` | `test_double_add_conflicts` | sweep (disabled person, H60) | | sweep | |
| Attachments | `test_upload_over_the_size_limit_is_rejected` | | `test_comment_attachment_visibility_follows_its_task` | | sweep | script-carrying files never render (H47) |
| Custom fields | `test_fields.py`, `test_field_filters.py` (every op × type) | | archived field values kept, undo (H55) | date fields as dates | sweep (H55) | |
| Tags | `test_tags.py` | `test_attaching_the_same_tag_twice_is_a_noop_not_a_conflict` | name reuse after delete (H54) | | sweep (H53) | |
| Multi-homing | `test_multi_homing.py` | | `test_private_co_placement_is_never_leaked_to_a_non_member` | | sweep | |
| Dependencies, rescheduling, timeline | `test_dependencies.py`, timeline 500 tasks | `test_duplicate_dependency_conflicts` | deleted blocker drops out (sweep) | `test_reschedule.py` (weekends, working days) | sweep | |
| Recurrence | `test_recurrence.py` | | | `test_monthly_day_of_month_last_day`, `test_yearly_leap_day_falls_back`, `test_spawning_pins_a_monthly_series_to_its_day` (H31); dates only, so DST can't move them | sweep | |
| My Tasks, Home, Inbox, notifications | `test_my_tasks.py`, `test_home.py`, `test_notifications.py` | | `test_hidden_work_limits_who_can_take_more` | buckets and digests in each person's timezone | sweep | `test_inbox_catch_up` |
| Search | `test_blank_query_returns_nothing` | | sweep | | | `test_search_tasks_filters_and_visibility` |
| Approvals, milestones | `test_approvals.py`, `test_milestones.py` | `test_deciding_twice_conflicts` | | | sweep | |
| Templates | `test_templates.py` | | | relative dates | | |
| Rules | `test_rules.py` (`test_depth_limit`, `test_rate_limit_per_project_per_minute`) | `test_edit_enable_and_version_conflicts` | `test_stale_target_that_no_longer_works_fails_the_action`, `test_rule_of_a_disabled_author_fails_instead_of_acting` | `test_rules.py` (due approaching, hourly) | delete (H56) | `test_a_test_run_changes_nothing` |
| Forms, intake | `test_forms.py`, `test_forms_security.py` | `test_crud_and_optimistic_concurrency` | deleted section (H59) | | delete (H56) | `test_public_form_is_rate_limited_per_ip`, `test_behind_a_proxy_the_rate_limit_follows_the_real_address` |
| Status updates | `test_ai_status.py` | | | | sweep | |
| Portfolios, goals | `test_portfolios.py`, `test_goals.py` | | archived project in a portfolio (sweep) | goal periods | sweep | numbers re-read per viewer |
| Workload | `test_workload.py`, load test (H36, H37) | | | weeks in the workspace timezone | sweep (capacity) | `test_hidden_work_limits_who_can_take_more` |
| Dashboards, forecasts | `test_series_fill_empty_buckets_and_drill_by_bucket`, `test_weekly_throughput_counts_empty_weeks` | | | `test_history_is_deterministic_and_the_backtest_is_calibrated` | sweep | numbers never in events |
| CSV and Asana import | `test_csv_import.py`, `test_asana_import.py` | | | | `test_a_rerun_duplicates_nothing` (idempotent), `test_a_dry_run_reports_and_writes_nothing` | token never stored |
| Export / import, backup | `test_portability.py` | | | | round trip byte-identical | restore rehearsed (S7.5.5) |
| Admin: members, jobs, audit | `test_admin.py` | | disable / re-enable, hand on work | | role and status changes undoable | |
| Agent schedules | `test_agent_runtime.py` | `test_two_workers_claiming_at_once_never_share_a_run` | `test_timeouts_and_handler_agents_fail_clearly` | `test_schedules_in_workspace_fixed_and_personal_timezones`, `test_a_schedule_in_the_repeated_hour_runs_once_when_the_clocks_go_back` (H62) | `test_too_many_undos_demote_an_agent_and_tell_the_admins` | |

## 3. AI features

| Feature | AI unavailable | Slow / partial streaming | Prompt injection | Permission leakage | Budget |
|---|---|---|---|---|---|
| Gateway (all features) | `test_llm.py::test_server_errors_retry_with_backoff_then_fail_as_unavailable`, `test_rate_limit_is_retried_honoring_retry_after` | `test_stream_that_drops_after_output_fails_instead_of_retrying` | | | `test_budget_is_checked_before_calling_and_resets_monthly`, `test_one_person_is_limited_per_hour_but_not_others_or_agents` (H38) |
| Ask Mo (chat) | `test_ai_off_ends_the_stream_with_an_error_event` | | evals `chat/hostile_comment_*` (S7.3.1) | `test_builders_respect_visibility`, `test_leak_check_ignores_words_the_asker_typed_but_not_citations`, `test_conversations_are_private` | sweep |
| ⌘K commands | `test_ai_command.py` | | evals `command/hostile_comment_not_executed`, `reading_task_text_changes_nothing` | `test_invisible_task_reads_like_a_missing_one` | sweep |
| Quick add, writing help, summaries | `test_ai_quick_add.py`, `test_ai_write.py` | | evals `summarize_thread/*`, `summarize_inbox/*` | `test_thread_needs_visibility_and_comments` | `test_blocks_stay_within_budget_on_huge_content` |
| Status drafts, goal check-ins | `test_a_quiet_week_drafts_nothing` | | evals `status_draft/hostile_*`, `goal_check_in/hostile_*` | `test_private_content_never_reaches_non_members` | sweep |
| Rules from words, AI steps | `test_ai_off_keeps_the_question_and_ends_with_an_error` | | evals `nl_rule/smuggled_instruction_ignored`, `ai_step/*hostile*` | `test_other_projects_resolve_only_where_visible` | sweep |
| Charts, rebalancing, from brief, breakdown, plan day | `test_nothing_to_plan`, `test_a_reply_the_schema_refuses_degrades_gracefully` | | evals per feature | `test_ai_chart.py`, `test_workload_rebalance.py` (hidden work) | sweep |
| Agents | `test_timeouts_and_handler_agents_fail_clearly` | | `test_an_injected_instruction_obeyed_by_the_model_still_changes_nothing`, evals `agent_sorter/form_injection_is_data` | `test_agent_detail_hides_private_projects_the_caller_cannot_see` | `test_a_one_cent_budget_stops_the_agent_and_alerts_the_admin` |

Live results of the AI evals: `phase-7.md` "As built: S7.3.2".
