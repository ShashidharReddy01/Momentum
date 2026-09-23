"""Health and runtime-config endpoints (no auth)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

from momentum.api.deps import RuntimeDep

VERSION = "0.1.0"

health_router = APIRouter(tags=["system"])
config_router = APIRouter(tags=["system"])


@health_router.get("/healthz", summary="Liveness and database check")
async def healthz(rt: RuntimeDep) -> dict[str, str]:
    async with rt.engine.connect() as conn:
        await conn.execute(text("select 1"))
    return {"status": "ok"}


@config_router.get("/config", summary="Runtime configuration for the SPA")
async def config(request: Request, rt: RuntimeDep) -> dict[str, Any]:
    s = rt.settings
    base = s.base_path
    return {
        "version": VERSION,
        "env": s.env,
        "base_path": base,
        "api_base": f"{base}/api/v1",
        "ai_enabled": s.ai_enabled,
        "auth": {
            "mode": s.auth_mode,
            "login_url": rt.auth.login_url(f"{base}/"),
            "dev_login": s.is_dev_auth,
        },
        "features": {"realtime": s.realtime_enabled},
    }
