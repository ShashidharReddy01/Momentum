# Phase 9: Integrations (after go-live)

> **Re-planned 2026-10-01 (product owner):** was Phase 7; moved after production ("bring this later even after set into production, it should work"). Slice ids S7.x → S9.x. **Slack first** (S9.2) when this phase starts; Outlook (S9.3), email-to-task (S9.4) and outgoing webhooks (S9.5) follow later, on demand. Everything here must be addable to the running production system as a settings change plus a deploy (the Easy Auth exclusion for `/webhooks/*` is already planned in S8.2.2). Add a short security check of the new endpoints to each slice, since they arrive after the Phase 7 security review.

**Goal:** Momentum works where people already are: Slack, Outlook calendar, email, and any MCP-capable AI client.

**Exit criteria:** create a task from a Slack message; daily digest arrives by Slack DM; Claude Desktop (or another MCP client) can list and update tasks with a personal token; the calendar shows focus blocks in Plan my day.

---

### S9.1: API tokens and MCP server (M) — **MCP dropped (product owner, 2026-09-26)**
**Decision:** no MCP server. **Personal API tokens moved to Phase 5 as S5.1.6** (product owner, 2026-09-28; ADR-0009), so nothing from S9.1 remains here.

**Scope:** settings UI for personal API tokens (create with scopes/expiry, shown once, revoke); FastMCP server at `/mcp` (streamable HTTP) exposing registry tools (read + write with the same preview/confirm semantics. Write tools return a proposal link unless the token has the `ai:auto_apply` scope); docs page "Connect Claude/VS Code to Momentum".
**AC:** a token without `tasks:write` can't create tasks; all MCP writes appear with `created_via=mcp`.

### S9.2: Slack app (L)
**Scope:** `integrations/slack` with Bolt for Python. Local: **Socket Mode** (`SLACK_APP_TOKEN`). Prod: Events API + interactivity at `/webhooks/slack` (Easy Auth excluded path, signature verification). Features: link Slack user ↔ Momentum user (by email); DM notifications (per user prefs); message shortcut "Create Momentum task" (modal: title prefilled, project, assignee, due) with backlink; link unfurls for task/project URLs (permission-checked: unfurl only if the Slack user maps to a Momentum user who can see it); `/momentum` slash command (`/momentum add …`, `/momentum my`); chat with Mo in DMs (read-only answers + proposals that open in Momentum to apply); rule action "post to channel" (high risk, confirm for agents).
**AC:** no Momentum content is revealed in Slack to users without access; Slack retries don't create duplicate tasks (idempotency by event id).

### S9.3: Outlook calendar via Microsoft Graph (M)
**Scope:** app registration (delegated or application permissions, decided at kickoff with IT constraints); read free/busy + events for linked users; Plan my day accounts for meetings and proposes focus blocks (optionally create tentative events. High risk, confirm); workload capacity reduces for OOO events.

### S9.4: Email-to-task (M)
**Scope:** per-project inbound address (`<project-slug>+<token>@<domain>`) via an inbound email webhook provider or a Graph mailbox poller (decided at kickoff); parse subject/body/attachments → task; Scribe agent option for meeting-notes emails; sender must be a workspace user (else rejected).

### S9.5: Outgoing webhooks (S)
**Scope:** workspace webhooks subscribing to event types; HMAC signature; retries with backoff; delivery log.

### S9.6 (optional, later): Code-host integration
**Scope:** link PRs/commits to tasks by key (`T-123`), auto-move on merge. Only if the team asks.
