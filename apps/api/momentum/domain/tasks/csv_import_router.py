from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, UploadFile

from momentum.api.deps import CtxDep, UowDep
from momentum.domain.access import get_visible_project
from momentum.domain.tasks.csv_import import (
    CsvColumnMapping,
    CsvImportResult,
    CsvPreview,
    import_csv,
    preview_csv,
)

router = APIRouter(tags=["tasks"])

MAX_CSV_BYTES = 5 * 1024 * 1024


async def _read_text(file: UploadFile) -> str:
    data = await file.read(MAX_CSV_BYTES + 1)
    return data.decode("utf-8-sig", errors="replace")


@router.post(
    "/projects/{project_id}/import/csv/preview",
    response_model=CsvPreview,
    summary="Headers + a sample of rows, for the column-mapping UI",
)
async def preview_csv_upload(
    project_id: uuid.UUID, ctx: CtxDep, uow: UowDep, file: UploadFile = File(...)
) -> CsvPreview:
    text = await _read_text(file)
    async with uow.transaction() as s:
        await get_visible_project(s, ctx, project_id)  # visible-to-caller check only
    return preview_csv(text)


@router.post(
    "/projects/{project_id}/import/csv",
    response_model=CsvImportResult,
    summary="Import tasks from a CSV using a column mapping",
)
async def commit_csv_import(
    project_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    file: UploadFile = File(...),
    mapping: str = Form(..., description="CsvColumnMapping, JSON-encoded"),
) -> CsvImportResult:
    parsed = CsvColumnMapping.model_validate_json(mapping)
    text = await _read_text(file)
    async with uow.transaction() as s:
        return await import_csv(s, ctx, project_id, text, parsed)
