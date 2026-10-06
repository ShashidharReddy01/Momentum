# Security

How Momentum meets OWASP ASVS Level 1, and the review that checked it (Phase 7, S7.5.2,
2026-10-06). The automated parts run in `make check` (`apps/api/tests/test_security.py`,
`test_api_robustness.py`, ruff's `S` rules); the dependency and secrets scans are run before
each release (commands below).

## Controls

| Area (ASVS) | How | Checked by |
|---|---|---|
| Authentication (V2, V3) | Production sign-in is Azure App Service Easy Auth with Entra ID; Momentum never sees a password. Sessions are the auth provider's; dev login exists only with `MOMENTUM_AUTH_MODE=dev`, which production refuses at startup. API tokens (`mtm_…`) are random, stored hashed, scoped and revocable. | settings validator tests; `test_api_tokens.py` |
| Access control (V4) | Every permission check is in the services (`core.permissions.can`, `domain/access.py`), so the UI, Mo, agents, rules, imports and the API enforce the same rules; realtime channels are re-authorized every 30 s and after access changes. **Every API operation refuses an anonymous caller** except a short, reviewed list (runtime config, dev sign-in, public forms). | `test_every_api_route_refuses_an_anonymous_caller`, `test_api_robustness.py` (every operation as admin and as a member), permission tests per feature, `test_realtime.py` |
| CSRF (V4.2) | A cookie session must send `X-Requested-With: momentum` on every change (a cross-site form can't); bearer tokens and the public form endpoints are exempt. | `test_a_cookie_session_needs_the_csrf_header_to_change_anything` |
| Input (V5) | Typed request models (`extra="forbid"`, lengths, patterns), rich text sanitized to an allow-list (`core/richtext.py`), NUL characters stripped, no raw SQL from input (custom-field and chart filters are typed data turned into expressions). | `test_api_robustness.py` (boundary values on every field) |
| Output / XSS (V5.3, V14.4) | React escapes everything; rich text renders from a sanitized document, never HTML. **Security headers on every response:** a page CSP that runs only Momentum's own scripts (no inline script, no eval), API responses with `default-src 'none'`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `frame-ancestors` / `X-Frame-Options` (`MOMENTUM_FRAME_ANCESTORS`), HSTS in production. | `test_security_headers`, `test_hsts_in_production_and_a_host_can_frame_momentum`; the e2e journeys run under the CSP |
| Files (V12) | Size limit (`MOMENTUM_MAX_UPLOAD_MB`), the type is recognised from the bytes, downloads check task visibility. **Only formats that can't carry script (PNG, JPEG, GIF, WebP, AVIF, PDF) and whose bytes match are shown inline;** everything else (SVG, HTML, text…) downloads, with a sandbox CSP and `nosniff`. File names are sent safely (ASCII fallback + RFC 5987). Virus scanning: not built; on Azure, Defender for Storage covers the blob store (Phase 8). | `test_a_file_that_could_carry_script_never_renders`, `test_attachments.py` |
| Rate limits (V11) | Public forms per IP and per form; AI: a workspace monthly budget, per-agent budgets and `MOMENTUM_AI_USER_CALLS_PER_HOUR` per person; sign-in is Entra's. | `test_forms_*`, `test_ai_admin.py` |
| Secrets (V6, V14.1) | Every secret is a setting (Key Vault in production, never in code); logs never carry tokens or prompt bodies; the Asana token is never stored (it's sent with each import step). | ruff `S`, `detect-secrets`, history scan |
| AI (prompt injection) | User and external content goes into prompts as data (`<data>` blocks), Mo's and agents' writes go through preview → confirm → apply with undo, and agents can only use their declared tools within their budgets. | `docs/ai/ai-architecture.md` §8; E7.3 adds the injection fixtures |
| Dependencies (V14.2) | Locked (`uv.lock`, `pnpm-lock.yaml`), audited. | `pip-audit`, `pnpm audit` (below) |

## Review 2026-10-06 (S7.5.2)

- **Found and fixed (hardening register H47–H49):** SVG files were shown inline from Momentum's
  origin when the uploader called them images (stored XSS, **P0**); no security headers at all
  (**P1**); a file name with a quote could break the download header (P3).
- **Scans, all clean:** `pip-audit` on the locked runtime requirements and `pnpm audit`: no known
  vulnerabilities; Semgrep (`p/python`, `p/react`, `p/typescript`, `p/secrets`): two reviewed
  `text()` calls in migrations (setting-derived schema name, not input); `detect-secrets` on the
  working tree: only dev and test placeholders (local Postgres passwords, `dev-only-change-me`, fake
  keys in tests); the git history has no real-looking keys (OpenAI/AWS/Slack/GitHub/JWT patterns);
  no `.env` was ever committed.
- **Anonymous access:** every one of the API's operations was called without a session; only the
  reviewed public list answered.

### Commands

```bash
cd apps/api && uv export --frozen --no-dev --no-hashes --format requirements-txt --no-emit-project > /tmp/req.txt && uvx pip-audit -r /tmp/req.txt --no-deps
cd apps/web && pnpm audit --prod
uvx semgrep scan --config p/python --config p/react --config p/typescript --config p/secrets --metrics off apps/api/momentum apps/web/src
uvx detect-secrets scan --exclude-files '(node_modules|\.venv|dist|pnpm-lock\.yaml|uv\.lock|schema\.d\.ts)'
```
