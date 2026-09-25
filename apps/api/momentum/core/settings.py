"""Runtime configuration. Every setting is documented in docs/architecture/configuration.md."""

from __future__ import annotations

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
    worker_concurrency: int = 4
    realtime_enabled: bool = True

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

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.env == "production":
            if self.auth_mode in ("dev", "easyauth-sim"):
                raise ValueError("MOMENTUM_AUTH_MODE dev/easyauth-sim is not allowed in production")
            if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
                raise ValueError("MOMENTUM_SECRET_KEY must be set (>=32 chars) in production")
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
    def events_channel(self) -> str:
        return f"{self.db_schema}_events"

    @property
    def psycopg_conninfo(self) -> str:
        """Plain libpq URL (without the SQLAlchemy driver suffix) for psycopg/procrastinate."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def search_path(self) -> str:
        return f"{self.db_schema},public"
