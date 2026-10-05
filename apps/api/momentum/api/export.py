"""S7.5.1: an admin downloads the workspace's export bundle (the same as `momentum export`)."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Query
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.core.permissions import Action, require
from momentum.core.storage import build_storage
from momentum.portability import cleanup, export_to, zip_bundle

router = APIRouter(tags=["admin"])


@router.get(
    "/admin/export",
    response_class=FileResponse,
    summary="Download everything as an export bundle (.zip; admins)",
)
async def download_export(
    ctx: CtxDep,
    uow: UowDep,
    rt: RuntimeDep,
    files: bool = Query(default=False, description="Include every attachment's file"),
) -> FileResponse:
    require(ctx, Action.WORKSPACE_ADMIN)
    work = Path(tempfile.mkdtemp(prefix="momentum-export-"))
    async with uow.transaction() as s:
        await export_to(
            s,
            work / "bundle",
            storage=build_storage(rt.settings) if files else None,
            with_files=files,
        )
    name = f"momentum-export-{datetime.now(UTC):%Y%m%d-%H%M}.zip"
    zip_bundle(work / "bundle", work / name)
    return FileResponse(
        work / name,
        media_type="application/zip",
        filename=name,
        background=BackgroundTask(cleanup, work),  # the files go once they're sent
    )
