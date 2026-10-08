"""Test-only packs (echo, asker, failer, spawner, consultee, planner_fixture), loaded only when
MOMENTUM_TEST_PACKS=true (never in production). Each exercises one platform mechanic — jobs,
asks, children, consult, plan bindings — so the platform's own tests don't depend on Bernie.

Empty until S76-02+ builds the first fixture pack (durable jobs); see
docs/superpowers/specs/2026-10-06-phase-7-6-agent-platform-bernie-design.md §14.2.
"""
