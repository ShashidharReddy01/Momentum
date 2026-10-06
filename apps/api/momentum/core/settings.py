"""Runtime configuration. Every setting is documented in docs/architecture/configuration.md."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Env = Literal["local", "test", "production"]
AuthMode = Literal["dev", "easyauth-sim", "easyauth", "oidc", "host"]
WorkerMode = Literal["embedded", "separate", "off"]
LLMMode = Literal["gateway", "mock", "record"]


DEV_SECRET = "dev-only-change-me"  # noqa: S105 - rejected in production by the validator


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _json_str_map(value: str, name: str) -> dict[str, str]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"{name} must be a JSON object") from e
    if not isinstance(parsed, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()
    ):
        raise ValueError(f"{name} must be a JSON object of string values")
    return parsed


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOMENTUM_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Core
    env: Env = "local"
    secret_key: str = DEV_SECRET
    base_path: str = ""
    public_base_url: str = "http://localhost:5173"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    default_workspace_slug: str = "default"
    default_workspace_name: str = "Momentum"
    serve_spa: bool = True
    spa_dir: str | None = None

    # Storage (S2.6.1)
    storage_backend: Literal["local", "azure_blob"] = "local"
    storage_local_dir: str = "./.data/files"
    max_upload_mb: int = 50

    # Database
    database_url: str = "postgresql+psycopg://momentum:momentum@localhost:5432/momentum"
    db_schema: str = Field(default="momentum", pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_auto_migrate: bool = False

    # S7.5.2: security headers on every response (core/http.py). A host that embeds Momentum
    # and sets its own can turn them off; frame_ancestors says who may frame Momentum's pages
    # (CSP frame-ancestors sources); content_security_policy replaces the default page CSP.
    security_headers: bool = True
    frame_ancestors: str = Field(default="'self'", max_length=500)
    content_security_policy: str = Field(default="", max_length=4000)

    # Auth
    auth_mode: AuthMode = "dev"
    allowed_tenant_ids: str = ""
    allowed_email_domains: str = ""
    bootstrap_admin_emails: str = ""
    admin_role: str = "Momentum.Admin"
    sync_admin_role: bool = True
    identity_link_by_email: bool = True
    auto_provision: bool = True
    easyauth_email_claims: str = (
        "preferred_username,email,upn,"
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
    )
    easyauth_trust_headers: bool = False
    easyauth_sim_tenant_id: str = "00000000-0000-4000-8000-00000000cafe"
    api_tokens_enabled: bool = True

    # Worker / realtime
    worker_mode: WorkerMode = "embedded"
    # Web server processes (`momentum serve`): one handles ~20 requests/s; ~150 active people
    # need 3-4 (Phase 7 load test). Realtime and the job queue already work across processes.
    web_workers: int = Field(default=1, ge=1, le=32)
    worker_concurrency: int = 4
    realtime_enabled: bool = True
    # S4.1.1: kill switch for the rules executor (rules stay editable; nothing fires)
    rules_enabled: bool = True

    # S4.2.1: public form spam limits. A submission is throttled per (form, hashed submitter
    # IP) and, separately, per form overall, so a single spoofed-IP flood is still bounded.
    forms_ip_hash_salt: str = "dev-only-change-me"
    forms_rate_limit_per_ip: int = Field(default=5, ge=1)
    forms_rate_limit_per_form: int = Field(default=60, ge=1)
    forms_rate_limit_window_minutes: int = Field(default=10, ge=1)
    # S5.0.2: reverse proxies in front of the app that append to X-Forwarded-For (Azure App
    # Service: 1). 0 = none: the connection's own address is the client. The client address is
    # taken that many entries from the right of the header, so a visitor can't forge it.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    # AI (used from Phase 3)
    ai_enabled: bool = True
    llm_mode: LLMMode = "mock"
    llm_base_url: str = "http://localhost:4000/v1"
    llm_api_key: str = ""
    llm_model_fast: str = "claude-fast"
    llm_model_default: str = "claude-default"
    llm_model_smart: str = "claude-smart"
    llm_embed_model: str = "cohere-embed-v3"
    llm_embed_dim: int = 1024
    llm_embed_batch: int = Field(default=96, ge=1)
    llm_timeout_s: float = Field(default=60, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)
    llm_supports_streaming_tools: bool = True
    # S3.1.4: optional rerank after hybrid retrieval (Cohere rerank via the gateway), off by
    # default; `llm-check` probes the model either way.
    llm_rerank_model: str = "cohere-rerank-v3.5"
    ai_rerank: bool = False
    # S3.1.1: gateways differ in how they take their key. LiteLLM uses the standard
    # "Authorization: Bearer <key>"; some (e.g. Portkey) want it in their own header. Any other
    # value sends the raw key in that header instead (the SDK's bearer header carries it too).
    llm_api_key_header: str = "Authorization"
    # JSON object of extra, non-secret headers sent on every gateway call (e.g. a gateway's
    # provider/config routing header). Keep secrets in MOMENTUM_LLM_API_KEY, never here.
    llm_extra_headers: str = "{}"
    # JSON `{model: {in_per_mtok, out_per_mtok}}` (USD) used for llm_calls cost estimates.
    llm_price_table: str = "{}"
    # Mock/record fixture directory; empty = the packaged ai/evals/fixtures/mock_responses.
    llm_fixtures_dir: str = ""
    # S3.5.1: the throwaway database `momentum evals` resets (its name must end in _evals);
    # empty = the main database's name + "_evals" on the same server
    evals_database_url: str = ""
    ai_monthly_budget_usd: float = Field(default=0, ge=0)  # 0 = unlimited
    # Phase 7 S7.1.1: one person's own model calls per rolling hour (a chat turn with tools makes
    # a few); agent runs have their own budgets. 0 = unlimited.
    ai_user_calls_per_hour: int = Field(default=200, ge=0)

    # S5.1.1: ceilings for every agent's per-run limits (ai-architecture §10). An agent's own
    # `limits` may be lower, never higher.
    # S5.1.2: kill switch for the agent scheduler, event consumer and runner (agents stay
    # editable; nothing runs). The global AI switch and each agent's `enabled` apply as well.
    agents_enabled: bool = True
    # S5.1.5 (ADR-0009): a host's agent extensions, "package.module:attribute" (an Extensions
    # object or a function returning one): extra tools, handler agents, definition directories.
    agent_extensions: str = ""
    agent_max_steps: int = Field(default=15, ge=1, le=50)
    agent_timeout_s: int = Field(default=300, ge=10, le=3600)

    # S6.4.1: the weekly hours a person can plan against when neither they nor the workspace
    # admin has set one (workload view, Architect's capacity notes).
    workload_default_hours: float = Field(default=30, ge=0, le=80)
    # S6.5.3: Monte Carlo runs per project forecast, and the nightly job's kill switch (a
    # forecast can still be refreshed from a project's overview when it's off).
    forecast_runs: int = Field(default=10_000, ge=100, le=200_000)
    forecasts_enabled: bool = True

    # Integrations (S2.7.1) — overridable so J6's e2e journey can point this at a local recorded
    # fixture server instead of the real Asana API (see tools/e2e/asana_fixture_server.py).
    asana_base_url: str = "https://app.asana.com/api/1.0"

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.env == "production":
            if self.auth_mode in ("dev", "easyauth-sim"):
                raise ValueError("MOMENTUM_AUTH_MODE dev/easyauth-sim is not allowed in production")
            if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
                raise ValueError("MOMENTUM_SECRET_KEY must be set (>=32 chars) in production")
            if self.ai_enabled and self.llm_mode != "gateway":
                # Never a silent fallback to mock AI output in production (CLAUDE.md §3).
                raise ValueError("MOMENTUM_LLM_MODE must be 'gateway' in production")
            if self.forms_ip_hash_salt == "dev-only-change-me":
                raise ValueError("MOMENTUM_FORMS_IP_HASH_SALT must be set in production")
        _json_str_map(self.llm_extra_headers, "MOMENTUM_LLM_EXTRA_HEADERS")
        self.base_path = self.base_path.rstrip("/")
        if self.base_path and not self.base_path.startswith("/"):
            raise ValueError("MOMENTUM_BASE_PATH must start with '/'")
        return self

    # Derived helpers
    @property
    def is_dev_auth(self) -> bool:
        return self.auth_mode in ("dev", "easyauth-sim")

    @property
    def allowed_tenants(self) -> list[str]:
        return _csv(self.allowed_tenant_ids)

    @property
    def allowed_domains(self) -> list[str]:
        return [d.lower() for d in _csv(self.allowed_email_domains)]

    @property
    def bootstrap_admins(self) -> list[str]:
        return [e.lower() for e in _csv(self.bootstrap_admin_emails)]

    @property
    def email_claims(self) -> list[str]:
        return _csv(self.easyauth_email_claims)

    @property
    def llm_headers(self) -> dict[str, str]:
        """Parsed MOMENTUM_LLM_EXTRA_HEADERS (validated at startup)."""
        return _json_str_map(self.llm_extra_headers, "MOMENTUM_LLM_EXTRA_HEADERS")

    @property
    def events_channel(self) -> str:
        return f"{self.db_schema}_events"

    @property
    def psycopg_conninfo(self) -> str:
        """Plain libpq URL (without the SQLAlchemy driver suffix) for psycopg/procrastinate."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def search_path(self) -> str:
        return f"{self.db_schema},public"
