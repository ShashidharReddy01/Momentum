"""S2.7.2: CSV import (`docs/roadmap/phase-2.md`'s S2.7.2 line: "upload CSV → column mapping UI
→ preview → import into a project (sections from a column optional)").

Kept in its own module rather than folded into `tasks/service.py` (already the largest service
file in the codebase) — but reuses that module's own `create_task`/`set_completed` directly for
each row, rather than reimplementing task creation, so a CSV-imported task gets exactly the same
validation, activity trail, undo entry, and realtime event a manually-created task gets. That's a
deliberate choice over the Asana importer's own direct-ORM approach: CSV rows come from a trusted
in-app upload (not a bulk cross-system sync with its own identity/idempotency model), so there's
no analogous reason to bypass the normal task-creation path here.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import ValidationFailed
from momentum.domain.access import get_visible_project, require_project_role
from momentum.domain.integrations.models import ImportJob
from momentum.domain.sections.service import create_section, list_sections
from momentum.domain.tasks.service import create_task, set_completed
from momentum.domain.users.models import User

MAX_PREVIEW_ROWS = 10
COMPLETED_TRUE_VALUES = {"true", "1", "yes", "y", "done", "completed", "x"}


class CsvPreview(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    row_count: int


class CsvColumnMapping(BaseModel):
    title_col: str
    section_col: str | None = None
    assignee_email_col: str | None = None
    due_on_col: str | None = None
    completed_col: str | None = None


class CsvImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]


def _read_rows(csv_text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def preview_csv(csv_text: str) -> CsvPreview:
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    headers = rows[0] if rows else []
    body = rows[1:]
    return CsvPreview(headers=headers, rows=body[:MAX_PREVIEW_ROWS], row_count=len(body))


async def _user_by_email(session: AsyncSession, ctx: Ctx, email: str) -> uuid.UUID | None:
    user = (
        await session.execute(
            select(User).where(
                User.workspace_id == ctx.workspace_id, func.lower(User.email) == email.lower()
            )
        )
    ).scalar_one_or_none()
    return user.id if user else None


async def import_csv(
    session: AsyncSession,
    ctx: Ctx,
    project_id: uuid.UUID,
    csv_text: str,
    mapping: CsvColumnMapping,
) -> CsvImportResult:
    # Checked once, upfront: every row below calls `create_task`, which repeats this same check
    # per row, but a caller with no access to the project shouldn't be able to tell an "import
    # succeeded with everything skipped" apart from "access denied" — only `ValidationFailed`
    # (a bad row) is caught per row below; a permission error propagates as a real HTTP error.
    _, role = await get_visible_project(session, ctx, project_id)
    require_project_role(role, "editor", "import tasks")
    assert ctx.actor.id is not None
    job = ImportJob(
        workspace_id=ctx.workspace_id, source="csv", status="running", started_by=ctx.actor.id
    )
    session.add(job)
    rows = _read_rows(csv_text)
    section_by_name: dict[str, uuid.UUID] = {
        s.name: s.id for s in await list_sections(session, project_id)
    }
    created = 0
    skipped = 0
    errors: list[str] = []

    for i, row in enumerate(rows, start=1):
        title = row.get(mapping.title_col, "").strip()
        if not title:
            skipped += 1
            errors.append(f"row {i}: missing title")
            continue

        section_id: uuid.UUID | None = None
        if mapping.section_col:
            name = row.get(mapping.section_col, "").strip()
            if name:
                if name not in section_by_name:
                    section_m = await create_section(session, ctx, project_id, name)
                    section_by_name[name] = section_m.entity.id
                section_id = section_by_name[name]

        assignee_id: uuid.UUID | None = None
        if mapping.assignee_email_col:
            email = row.get(mapping.assignee_email_col, "").strip()
            if email:
                assignee_id = await _user_by_email(session, ctx, email)
                if assignee_id is None:
                    errors.append(f"row {i}: no workspace member with email {email!r}")

        due_on: date | None = None
        if mapping.due_on_col:
            raw = row.get(mapping.due_on_col, "").strip()
            if raw:
                try:
                    due_on = date.fromisoformat(raw)
                except ValueError:
                    errors.append(f"row {i}: unrecognized date {raw!r} (expected YYYY-MM-DD)")

        try:
            task_m = await create_task(
                session,
                ctx,
                project_id,
                title,
                section_id=section_id,
                assignee_id=assignee_id,
                due_on=due_on,
            )
        except ValidationFailed as e:
            skipped += 1
            errors.append(f"row {i}: {e}")
            continue

        created += 1
        if mapping.completed_col:
            value = row.get(mapping.completed_col, "").strip().lower()
            if value in COMPLETED_TRUE_VALUES:
                task, _ = task_m.entity
                await set_completed(session, ctx, task.id, True, force=True)

    job.status = "done"
    job.stats = {"created": created, "skipped": skipped, "errors": len(errors)}
    job.finished_at = datetime.now(UTC)
    return CsvImportResult(created=created, skipped=skipped, errors=errors)
