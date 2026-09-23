"""Serve the built React SPA with an index.html fallback for client-side routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from momentum.core.settings import Settings

DEFAULT_DIR = Path(__file__).parent / "static"
RESERVED = ("api/", "ws", "mcp", "webhooks/", "healthz", ".auth/")


def resolve_spa_dir(settings: Settings) -> Path | None:
    candidate = Path(settings.spa_dir) if settings.spa_dir else DEFAULT_DIR
    return candidate if (candidate / "index.html").is_file() else None


def mount_spa(app: FastAPI, spa_dir: Path) -> None:
    assets = spa_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="spa-assets")
    index = spa_dir / "index.html"
    root = spa_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith(RESERVED):
            raise HTTPException(status_code=404)
        file = _static_file(root, full_path)
        if file is not None:
            return FileResponse(file)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def _static_file(root: Path, full_path: str) -> Path | None:
    """Return a real file inside ``root`` for top-level static files (favicon etc.)."""
    if not full_path:
        return None
    file = (root / full_path).resolve()
    return file if root in file.parents and file.is_file() else None
