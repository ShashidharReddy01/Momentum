"""S4.1.1: rules API. The builder UI (S4.1.3) and NL compile (S4.1.4) sit on top of this."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.domain.rules import service
from momentum.domain.rules.schemas import (
    ActionResultOut,
    RuleAiStepOut,
    RuleIn,
    RuleOut,
    RulePatchIn,
    RuleRunOut,
    RuleTestRunIn,
    RuleTestRunOut,
)

router = APIRouter(tags=["rules"])


@router.get(
    "/rules",
    response_model=ListOut[RuleOut],
    summary="Rules of a project (`project_id`), or the workspace's own rules when omitted",
)
async def list_rules(
    ctx: CtxDep, uow: UowDep, project_id: uuid.UUID | None = None
) -> ListOut[RuleOut]:
    async with uow.transaction() as s:
        rules = await service.list_rules(s, ctx, project_id)
        return ListOut(data=[RuleOut.model_validate(r) for r in rules])


@router.post(
    "/rules",
    response_model=MutationOut[RuleOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a rule (project admins; workspace admins for workspace rules)",
)
async def create_rule(body: RuleIn, ctx: CtxDep, uow: UowDep) -> MutationOut[RuleOut]:
    async with uow.transaction() as s:
        m = await service.create_rule(s, ctx, body)
        return MutationOut.of(m, RuleOut)


@router.get("/rules/{rule_id}", response_model=RuleOut, summary="One rule")
async def get_rule(rule_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> RuleOut:
    async with uow.transaction() as s:
        return RuleOut.model_validate(await service.get_rule(s, ctx, rule_id))


@router.patch(
    "/rules/{rule_id}",
    response_model=MutationOut[RuleOut],
    summary="Edit, enable or disable a rule",
)
async def patch_rule(
    rule_id: uuid.UUID, body: RulePatchIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[RuleOut]:
    async with uow.transaction() as s:
        m = await service.update_rule(s, ctx, rule_id, body)
        return MutationOut.of(m, RuleOut)


@router.delete(
    "/rules/{rule_id}", response_model=MutationOut[OkOut], summary="Delete a rule (history stays)"
)
async def delete_rule(rule_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_rule(s, ctx, rule_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.get(
    "/rules/{rule_id}/runs",
    response_model=ListOut[RuleRunOut],
    summary="A rule's recent runs, newest first",
)
async def list_runs(rule_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ListOut[RuleRunOut]:
    async with uow.transaction() as s:
        runs = await service.list_runs(s, ctx, rule_id)
        return ListOut(
            data=[
                RuleRunOut.model_validate(r).model_copy(
                    update={"ai_steps": [RuleAiStepOut.model_validate(st) for st in steps]}
                )
                for r, steps in runs
            ]
        )


@router.post(
    "/rules/{rule_id}/test-run",
    response_model=RuleTestRunOut,
    summary="Preview a rule's actions against a chosen task; nothing is persisted",
)
async def test_run(
    rule_id: uuid.UUID, body: RuleTestRunIn, ctx: CtxDep, uow: UowDep
) -> RuleTestRunOut:
    async with uow.transaction() as s:
        result = await service.test_run_rule(s, ctx, rule_id, body.task_id)
        return RuleTestRunOut(
            conditions_passed=result.conditions_passed,
            actions=[ActionResultOut(type=a.type, ok=a.ok, error=a.error) for a in result.actions],
        )
