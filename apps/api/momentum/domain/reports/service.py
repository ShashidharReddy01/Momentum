"""Phase 7.5 (spec §6.3): report runs. The one write path for generated reports.

- ``preview``: the outline (no file, no narrative), built as the requester.
- ``request_report``: checks the spec and that the requester may see the scope and add files where
  the report will live, then records a ``queued`` run.
- ``execute``: builds the document as the requester, adds the injected narrative, renders it,
  stores it as an attachment (``source='generated'``, ``generated_spec``) with the activity
  ``report.generated`` (undo deletes the file), and marks the run done (or failed, with the
  error in words).
- ``regenerate``: the stored spec again, as a new version of the same file.

Where a report lives: the project (project kinds, and a project's task export) or the portfolio
(portfolio kinds, a portfolio's task export, and a dashboard: its portfolio tab's, else its saved
portfolio filter's).
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.context import Ctx
from momentum.core.errors import Forbidden, NotFound, ValidationFailed
from momentum.core.events import emit
from momentum.core.ids import new_id
from momentum.core.storage import StorageBackend
from momentum.domain.access import get_visible_project, require_project_role
from momentum.domain.attachments.models import Attachment
from momentum.domain.attachments.service import create_attachment, get_visible_attachment
from momentum.domain.reports.models import ReportRun
from momentum.reports.generate import build, generate, outline
from momentum.reports.narrative import Narrator
from momentum.reports.render.text import render_md
from momentum.reports.spec import ReportSpec


def parse_spec(raw: dict[str, Any]) -> ReportSpec:
    try:
        return ReportSpec.model_validate(raw)
    except ValidationError as e:
        raise ValidationFailed(str(e.errors()[0].get("msg", "invalid report"))) from None


async def home_of(session: AsyncSession, ctx: Ctx, spec: ReportSpec) -> dict[str, uuid.UUID]:
    """Where the file will live (``project_id`` or ``portfolio_id``), checked for the requester:
    they must see the scope and be allowed to add files there."""
    from momentum.domain.dashboards.service import get_dashboard, saved_filters
    from momentum.domain.portfolios.service import get_portfolio, require_edit

    s = spec.scope
    if s.project_id is not None:
        _project, role = await get_visible_project(session, ctx, s.project_id)
        require_project_role(role, "editor", "add a report to this project")
        return {"project_id": s.project_id}
    portfolio_id = s.portfolio_id
    if s.dashboard_id is not None:
        d, _ = await get_dashboard(session, ctx, s.dashboard_id)
        portfolio_id = d.portfolio_id or saved_filters(d).portfolio_id
        if portfolio_id is None:
            raise ValidationFailed(
                "A dashboard report is kept with its portfolio: save a portfolio filter on this "
                "dashboard first",
                code="no_portfolio",
            )
    if portfolio_id is None:
        raise ValidationFailed("Pick the project or portfolio the report is about")
    p = await get_portfolio(session, ctx, portfolio_id)
    await require_edit(session, ctx, p)
    return {"portfolio_id": portfolio_id}


async def preview(session: AsyncSession, ctx: Ctx, spec: ReportSpec) -> dict[str, Any]:
    await home_of(session, ctx, spec)
    doc = await build(session, ctx, spec)
    return outline(doc, spec)


async def request_report(
    session: AsyncSession, ctx: Ctx, spec: ReportSpec, *, via: str = "ui"
) -> ReportRun:
    if ctx.actor.id is None:
        raise Forbidden("Only people and agents acting for them can make reports")
    await home_of(session, ctx, spec)
    run = ReportRun(
        workspace_id=ctx.workspace_id,
        requested_by=ctx.actor.id,
        kind=spec.kind,
        spec=spec.model_dump(mode="json", by_alias=True, exclude_none=True),
        status="queued",
        created_via=via,
    )
    session.add(run)
    await session.flush()
    return run


async def get_run(session: AsyncSession, ctx: Ctx, run_id: uuid.UUID) -> ReportRun:
    run = await session.get(ReportRun, run_id)
    if run is None or run.workspace_id != ctx.workspace_id:
        raise NotFound("Report not found")
    if run.requested_by != ctx.actor.id and not ctx.actor.is_admin:
        raise NotFound("Report not found")
    return run


async def _store(storage: StorageBackend, key: str, data: bytes) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield data

    await storage.save_stream(key, chunks())


async def execute(
    session: AsyncSession,
    ctx: Ctx,
    run: ReportRun,
    *,
    storage: StorageBackend,
    narrator: Narrator | None,
    timeout_s: int,
    batch_id: uuid.UUID | None = None,
) -> ReportRun:
    """Generate and store one run as its requester (``ctx``). Errors end the run as ``failed``
    with a readable reason instead of raising, so the caller can report it."""
    spec = parse_spec(run.spec)
    replace_id = run.replace_id
    run.status = "running"
    await session.flush()
    key = f"{ctx.workspace_id}/{new_id()}"
    try:
        async with session.begin_nested():
            home = await home_of(session, ctx, spec)
            made = await asyncio.wait_for(
                generate(session, ctx, spec, narrator=narrator), timeout=timeout_s
            )
            await _store(storage, key, made.data)
            m = await create_attachment(
                session,
                ctx,
                project_id=None if replace_id else home.get("project_id"),
                portfolio_id=None if replace_id else home.get("portfolio_id"),
                storage_key=key,
                filename=made.filename,
                mime=made.mime,
                size_bytes=len(made.data),
                sha256=hashlib.sha256(made.data).hexdigest(),
                replace_id=replace_id,
                source="generated",
                generated_spec={**run.spec, "ai_drafted": bool(made.doc.ai_paragraphs)},
                verb="report.generated",
                batch_id=batch_id,
            )
            # its text, for search and for Mo: the Markdown twin of what was rendered
            m.entity.text_extract = render_md(made.doc).decode("utf-8")[:200_000]
            m.entity.extract_status = "done"
    except TimeoutError:
        await storage.delete(key)
        return _failed(run, f"The report took longer than {timeout_s} s and was stopped")
    except (ValidationFailed, NotFound, Forbidden) as e:
        await storage.delete(key)
        return _failed(run, e.detail)
    run.status = "done"
    run.attachment_id = m.entity.id
    run.finished_at = datetime.now(UTC)
    await emit(
        session,
        ctx,
        type="report.generated",
        entity_type="report",
        entity_id=run.id,
        data={
            "attachment_id": str(m.entity.id),
            "kind": run.kind,
            **{k: str(v) for k, v in home.items()},
        },
        channels=[f"user:{run.requested_by}"],
        activity_id=m.activity_id,
    )
    await session.flush()
    return run


def _failed(run: ReportRun, reason: str) -> ReportRun:
    run.status = "failed"
    run.error = reason
    run.finished_at = datetime.now(UTC)
    return run


async def regenerate(
    session: AsyncSession, ctx: Ctx, attachment_id: uuid.UUID, *, via: str = "ui"
) -> tuple[ReportRun, Attachment]:
    """The file's stored spec again; the result becomes its next version."""
    att = await get_visible_attachment(session, ctx, attachment_id)
    if att.source != "generated" or not att.generated_spec:
        raise ValidationFailed("Only a generated report can be regenerated", code="not_generated")
    raw = {k: v for k, v in att.generated_spec.items() if k != "ai_drafted"}
    run = await request_report(session, ctx, parse_spec(raw), via=via)
    run.replace_id = att.id
    return run, att
