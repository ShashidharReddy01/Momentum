"""S5.1.1: install agents from definition files (Momentum's starters plus any host directories
passed to ``create_app``). Same service as ``momentum agents install``."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.agents import health, radar, runs_view
from momentum.agents.jobs import control
from momentum.agents.loader import DefinitionError, all_definitions
from momentum.agents.packs import setup as pack_setup
from momentum.agents.packs.registry import packs_of, sync_record_types
from momentum.agents.runtime import dry_run
from momentum.agents.triggers import request_run
from momentum.ai.agent_draft import MAX_DESCRIPTION, AgentDraftOut, draft_agent
from momentum.ai.ask_interpret import describe, interpret_reply
from momentum.ai.router import require_llm
from momentum.api.deps import CtxDep, RuntimeDep, UowDep
from momentum.api.schemas import ListOut
from momentum.core.context import Ctx
from momentum.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from momentum.core.permissions import Action, can
from momentum.domain.access import get_visible_project
from momentum.domain.agents import service
from momentum.domain.agents.models import AgentRun
from momentum.domain.agents.schemas import (
    FORBIDDEN_AGENT_TOOLS,
    InstallIn,
    InstallOut,
    InstallRowOut,
)
from momentum.domain.asks import service as asks_service
from momentum.domain.asks.schemas import InterpretIn, InterpretOut
from momentum.domain.pack_settings import service as settings_service
from momentum.domain.tasks.models import Task
from momentum.domain.users.models import User

router = APIRouter(tags=["agents"])


@router.post(
    "/agents/install",
    response_model=InstallOut,
    summary="Install or refresh agents from their definitions; new ones start disabled (admins)",
)
async def install_agents(
    body: InstallIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> InstallOut:
    try:
        definitions = all_definitions(runtime.agent_definition_dirs, packs_of(runtime))
    except DefinitionError as e:
        raise ValidationFailed(str(e)) from e
    async with uow.transaction() as s:
        results = await service.install_definitions(
            s, ctx, definitions, runtime.tools.names, keys=body.keys, force=body.force
        )
        await sync_record_types(s, ctx.workspace_id, packs_of(runtime), runtime.settings)
        return InstallOut(
            results=[
                InstallRowOut(key=r.key, outcome=r.outcome, agent_id=r.agent.id) for r in results
            ]
        )


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID | None = None
    task: str | None = Field(
        default=None, max_length=60, description="Or a task key (T-12), as people type it"
    )
    project_id: uuid.UUID | None = None
    text: str | None = Field(default=None, max_length=20_000)


class RunQueuedOut(BaseModel):
    run_id: uuid.UUID
    status: str


@router.post(
    "/agents/{agent_id}/run",
    response_model=RunQueuedOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run an agent now, on a task or project you can see; it starts within a minute",
)
async def run_agent(
    agent_id: uuid.UUID, body: RunIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> RunQueuedOut:
    async with uow.transaction() as s:
        agent = await service.get_agent(s, ctx, agent_id)
        task_id = body.task_id or (await _task_id(s, ctx, body.task) if body.task else None)
        run_id = await request_run(
            s,
            ctx,
            agent,
            task_id=task_id,
            project_id=body.project_id,
            text=body.text,
            packs=packs_of(runtime),
        )
        run = await s.get(AgentRun, run_id)
        return RunQueuedOut(run_id=run_id, status=run.status if run else "queued")


@router.get(
    "/agents/{agent_id}/runs",
    response_model=ListOut[runs_view.AgentRunOut],
    summary="An agent's recent runs you may see, newest first (filter by status or trigger)",
)
async def list_agent_runs(
    agent_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    status: str | None = None,
    trigger: str | None = None,
) -> ListOut[runs_view.AgentRunOut]:
    async with uow.transaction() as s:
        return ListOut(
            data=await runs_view.list_runs(s, ctx, agent_id, status=status, trigger=trigger)
        )


@router.get(
    "/agents/runs/{run_id}",
    response_model=runs_view.AgentRunDetailOut,
    summary="One run: its steps, proposals, answer, cost and errors",
)
async def get_agent_run(
    run_id: uuid.UUID, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> runs_view.AgentRunDetailOut:
    async with uow.transaction() as s:
        return await runs_view.get_run(s, ctx, run_id, packs=packs_of(runtime))


# ---------- Phase 7.6 S76-02 (spec §4.3, §4.7): controlling a durable job ----------


class RunStateOut(BaseModel):
    run_id: uuid.UUID
    status: str


@router.post(
    "/agents/runs/{run_id}/retry",
    response_model=RunStateOut,
    summary="Retry a failed job from the step that failed (the person who asked, or an admin)",
)
async def retry_job(run_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> RunStateOut:
    async with uow.transaction() as s:
        run = await control.retry(s, ctx, run_id)
        return RunStateOut(run_id=run.id, status=run.status)


@router.post(
    "/agents/runs/{run_id}/cancel",
    response_model=RunStateOut,
    summary="Cancel a job and its open children (the person who asked, a project or workspace"
    " admin); what it wrote stays",
)
async def cancel_job(run_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> RunStateOut:
    async with uow.transaction() as s:
        run = await control.cancel(s, ctx, run_id)
        return RunStateOut(run_id=run.id, status=run.status)


@router.post(
    "/agents/runs/{run_id}/pause",
    response_model=RunStateOut,
    summary="Pause a job (workspace admins); a running pass stops at its next step",
)
async def pause_job(run_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> RunStateOut:
    async with uow.transaction() as s:
        run = await control.pause(s, ctx, run_id)
        return RunStateOut(run_id=run.id, status=run.status)


@router.post(
    "/agents/runs/{run_id}/resume",
    response_model=RunStateOut,
    summary="Resume a paused job (workspace admins)",
)
async def resume_job(run_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> RunStateOut:
    async with uow.transaction() as s:
        run = await control.resume(s, ctx, run_id)
        return RunStateOut(run_id=run.id, status=run.status)


class UndoSkippedOut(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    verb: str
    reason: str


class UndoAllOut(BaseModel):
    undone: int
    skipped: list[UndoSkippedOut]


@router.post(
    "/agents/runs/{run_id}/undo",
    response_model=UndoAllOut,
    summary="Undo everything a job and its children did, newest first, with your permissions;"
    " changes that can't be undone are listed",
)
async def undo_job(run_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> UndoAllOut:
    async with uow.transaction() as s:
        result = await control.undo_all(s, ctx, run_id)
        return UndoAllOut(
            undone=result.undone,
            skipped=[UndoSkippedOut.model_validate(x) for x in result.skipped],
        )


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)


@router.post(
    "/agents/draft",
    response_model=AgentDraftOut,
    summary="✦ Draft an agent from a description (admins); nothing is saved",
)
async def draft_agent_from_description(
    body: DraftIn, ctx: CtxDep, runtime: RuntimeDep
) -> AgentDraftOut:
    if not can(ctx, Action.WORKSPACE_ADMIN):
        raise Forbidden("Only workspace admins can create agents")
    llm = require_llm(runtime)
    return await draft_agent(llm, ctx.with_(via="ai"), runtime.tools, body.description)


class TestRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str | None = Field(
        default=None, max_length=60, description="A task id or key (T-12) to run on"
    )
    project_id: uuid.UUID | None = None
    text: str | None = Field(default=None, max_length=20_000)


class TestChangeOut(BaseModel):
    tool: str
    summary: str
    risk: str
    decision: str


class TestStepOut(BaseModel):
    kind: str
    summary: str
    name: str | None = None
    ok: bool | None = None


class TestRunOut(BaseModel):
    text: str
    steps: int
    trace: list[TestStepOut]
    changes: list[TestChangeOut]
    tokens_in: int
    tokens_out: int


async def _task_id(s: AsyncSession, ctx: Ctx, ref: str) -> uuid.UUID:
    ref = ref.strip()
    m = re.fullmatch(r"[Tt]-?(\d{1,9})", ref)
    if m is None:
        try:
            return uuid.UUID(ref)
        except ValueError as e:
            raise ValidationFailed("Give a task key like T-12") from e
    found = await s.scalar(
        select(Task.id).where(Task.workspace_id == ctx.workspace_id, Task.number == int(m[1]))
    )
    if found is None:
        raise NotFound("No task with that key")
    return found


@router.post(
    "/agents/{agent_id}/test-run",
    response_model=TestRunOut,
    summary="Test an agent on a task or project (admins): a dry run, nothing is changed",
)
async def test_run_agent(
    agent_id: uuid.UUID, body: TestRunIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> TestRunOut:
    if not can(ctx, Action.WORKSPACE_ADMIN):
        raise Forbidden("Only workspace admins can test agents")
    llm = require_llm(runtime)
    async with uow.transaction() as s:
        agent = await service.get_agent(s, ctx, agent_id)
        me = await s.get(User, ctx.actor.id)
        if me is None:
            raise NotFound()
        task_id = await _task_id(s, ctx, body.task) if body.task else None
        if task_id is None and body.project_id is None:
            raise ValidationFailed("Pick a task or a project to test on")
        out = await dry_run(
            s,
            llm,
            runtime.tools,
            runtime.settings,
            agent,
            me,
            task_id=task_id,
            project_id=body.project_id,
            text=body.text,
        )
        return TestRunOut.model_validate(out)


class AgentToolOut(BaseModel):
    name: str
    description: str
    risk: str


@router.get(
    "/agents/tools",
    response_model=ListOut[AgentToolOut],
    summary="The tools an agent can be given (for the agent form)",
)
async def list_agent_tools(ctx: CtxDep, runtime: RuntimeDep) -> ListOut[AgentToolOut]:
    _ = ctx  # members only (the dependency authenticates)
    return ListOut(
        data=[
            AgentToolOut(name=t.spec.name, description=t.spec.description, risk=t.spec.risk)
            for n in runtime.tools.names
            if (t := runtime.tools.get(n)) is not None and n not in FORBIDDEN_AGENT_TOOLS
        ]
    )


class RiskSignalOut(BaseModel):
    kind: str
    text: str
    tasks: list[str]


class RiskNoteOut(BaseModel):
    level: str
    summary: str
    signals: list[RiskSignalOut]
    at: datetime
    run_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str


@router.get(
    "/projects/{project_id}/risk",
    response_model=RiskNoteOut | None,
    summary="Radar's latest risk note on a project (S5.3.7); null when there is none",
)
async def project_risk(project_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> RiskNoteOut | None:
    async with uow.transaction() as s:
        await get_visible_project(s, ctx, project_id)
        return await latest_risk(s, ctx.workspace_id, project_id)


async def latest_risk(
    s: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> RiskNoteOut | None:
    found = await radar.latest_note(s, workspace_id, project_id)
    if found is None:
        return None
    run, agent = found
    risk = (run.output or {}).get("risk") or {}
    return RiskNoteOut(
        level=str(risk.get("level", "none")),
        summary=str(risk.get("summary", "")),
        signals=[RiskSignalOut.model_validate(x) for x in risk.get("signals", [])],
        at=run.finished_at or run.created_at,
        run_id=run.id,
        agent_id=agent.id,
        agent_name=agent.name,
    )


# ---------- Phase 7.6 (spec §3.4): a pack's project setup ----------


class SetupChangeOut(BaseModel):
    kind: str
    name: str
    action: str = Field(description="create · attach · exists · skip")
    detail: str


class SetupPreviewOut(BaseModel):
    agent_id: uuid.UUID
    project_id: uuid.UUID
    changes: list[SetupChangeOut]


class SetupApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID


class SetupAppliedOut(SetupPreviewOut):
    batch_id: uuid.UUID | None = Field(
        default=None,
        description="Undo the whole setup with POST /undo {batch_id}; null = no change",
    )


def _changes(changes: list[pack_setup.SetupChange]) -> list[SetupChangeOut]:
    return [
        SetupChangeOut(kind=c.kind, name=c.name, action=c.action, detail=c.detail) for c in changes
    ]


@router.get(
    "/agents/{agent_id}/setup",
    response_model=SetupPreviewOut,
    summary="Preview a pack agent's project setup (fields and sections it needs); changes nothing",
)
async def preview_setup(
    agent_id: uuid.UUID, project_id: uuid.UUID, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> SetupPreviewOut:
    async with uow.transaction() as s:
        agent = await service.get_agent(s, ctx, agent_id)
        items = await pack_setup.items_for(s, agent, project_id, packs_of(runtime))
        changes = await pack_setup.preview(s, ctx, project_id, items)
        return SetupPreviewOut(agent_id=agent.id, project_id=project_id, changes=_changes(changes))


@router.post(
    "/agents/{agent_id}/setup",
    response_model=SetupAppliedOut,
    summary="Apply a pack agent's project setup as one undoable batch (project admins)",
)
async def apply_setup(
    agent_id: uuid.UUID, body: SetupApplyIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> SetupAppliedOut:
    async with uow.transaction() as s:
        agent = await service.get_agent(s, ctx, agent_id)
        items = await pack_setup.items_for(s, agent, body.project_id, packs_of(runtime))
        result = await pack_setup.apply(s, ctx, body.project_id, items)
        return SetupAppliedOut(
            agent_id=agent.id,
            project_id=body.project_id,
            changes=_changes(result.changes),
            batch_id=result.batch_id,
        )


# ---------- Phase 7.6 S76-03 (spec §5.3): a thread reply as the answer to an ask ----------


@router.post(
    "/asks/{ask_id}/interpret",
    response_model=InterpretOut,
    summary="Read a thread reply as the answer: applied when certain (an exact option, yes/no, a"
    " lone number, text), otherwise returned for the person to confirm",
)
async def interpret_ask_reply(
    ask_id: uuid.UUID, body: InterpretIn, ctx: CtxDep, uow: UowDep, runtime: RuntimeDep
) -> InterpretOut:
    async with uow.transaction() as s:
        ask = await asks_service.get_ask(s, ctx, ask_id)
        if ctx.actor.role == "guest" or ctx.actor.id not in ask.to_user_ids:
            raise Forbidden("This question is for someone else")
        if ask.status != "open":
            raise Conflict(f"This question is {ask.status}", code="ask_closed")
        certain, value = asks_service.exact_answer(ask, body.text)
        if certain:
            ask = await asks_service.answer_ask(s, ctx, ask.id, value, via="thread")
            return InterpretOut(
                applied=True,
                certain=True,
                value=ask.answer,
                understood=describe(ask, ask.answer),
                ask=await asks_service.ask_out(s, ctx, ask),
            )
    llm = require_llm(runtime)
    reading = await interpret_reply(llm, ctx.with_(via="ai"), ask, body.text)
    async with uow.transaction() as s:
        fresh = await asks_service.get_ask(s, ctx, ask_id)
        return InterpretOut(
            applied=False,
            certain=False,
            value=reading.value,
            understood=reading.understood,
            ask=await asks_service.ask_out(s, ctx, fresh),
        )


# ---------- Phase 7.6 S76-05 (spec §8.3): a pack agent's settings ----------


class PackSettingsOut(BaseModel):
    agent_id: uuid.UUID
    pack_key: str
    project_id: uuid.UUID | None
    form: dict[str, Any] = Field(description="The settings' JSON Schema (the form to render)")
    workspace: dict[str, Any] = Field(description="The workspace's own values")
    project: dict[str, Any] | None = Field(description="This project's own values")
    effective: dict[str, Any] = Field(description="Defaults, then workspace, then project")
    can_edit: bool


class PackSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any]


async def _settings_out(
    s: AsyncSession, ctx: Ctx, agent: Any, model: Any, project_id: uuid.UUID | None
) -> PackSettingsOut:
    ws, proj = await settings_service.stored(s, ctx.workspace_id, agent.pack_key, project_id)
    return PackSettingsOut(
        agent_id=agent.id,
        pack_key=agent.pack_key,
        project_id=project_id,
        form=model.model_json_schema(),
        workspace=ws,
        project=proj if project_id else None,
        effective=settings_service.effective(model, ws, proj).model_dump(mode="json"),
        can_edit=await settings_service.can_edit(s, ctx, agent.pack_key, project_id),
    )


def _pack_settings_model(runtime: Any, agent: Any) -> Any:
    if agent.kind != "pack" or not agent.pack_key:
        raise ValidationFailed(f"{agent.name} isn't a pack agent, so it has no pack settings")
    pack = packs_of(runtime).packs.get(agent.pack_key)
    if pack is None:
        raise Conflict(f"{agent.name}'s pack isn't loaded on this server", code="pack_not_loaded")
    return pack.settings


@router.get(
    "/agents/{agent_id}/settings",
    response_model=PackSettingsOut,
    summary="A pack agent's settings: the form, the workspace and project values, the result",
)
async def get_pack_settings(
    agent_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    runtime: RuntimeDep,
    project_id: uuid.UUID | None = None,
) -> PackSettingsOut:
    async with uow.transaction() as s:
        if ctx.actor.role == "guest":
            raise Forbidden("Guests can't see agents' settings")
        agent = await service.get_agent(s, ctx, agent_id)
        model = _pack_settings_model(runtime, agent)
        if project_id is not None:
            await get_visible_project(s, ctx, project_id)
        return await _settings_out(s, ctx, agent, model, project_id)


@router.put(
    "/agents/{agent_id}/settings",
    response_model=PackSettingsOut,
    summary="Set a pack agent's workspace values (admins, stewards) or a project's (its admins);"
    " keys left out fall back",
)
async def put_pack_settings(
    agent_id: uuid.UUID,
    body: PackSettingsIn,
    ctx: CtxDep,
    uow: UowDep,
    runtime: RuntimeDep,
    project_id: uuid.UUID | None = None,
) -> PackSettingsOut:
    async with uow.transaction() as s:
        agent = await service.get_agent(s, ctx, agent_id)
        model = _pack_settings_model(runtime, agent)
        await settings_service.put_values(
            s, ctx, model, str(agent.pack_key), project_id, body.values
        )
        return await _settings_out(s, ctx, agent, model, project_id)


# ---------- Phase 7.6 S76-06 (spec §8.8): an agent's health ----------


@router.get(
    "/agents/{agent_id}/health",
    response_model=health.HealthOut,
    summary="An agent's health over the last N days (members: summary; admins, stewards: detail)",
)
async def agent_health(
    agent_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    runtime: RuntimeDep,
    days: int = Query(default=30, ge=1, le=365),
) -> health.HealthOut:
    async with uow.transaction() as s:
        agent = await service.get_agent(s, ctx, agent_id)
        return await health.compute(s, ctx, agent, packs_of(runtime), days)
