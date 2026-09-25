from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.api.deps import CtxDep, UowDep
from momentum.api.schemas import ListOut, MutationMeta, MutationOut, OkOut
from momentum.core.errors import ValidationFailed
from momentum.core.ids import task_key
from momentum.core.richtext import doc_hash
from momentum.domain.projects.models import Project
from momentum.domain.sections.models import Section
from momentum.domain.tasks import service
from momentum.domain.tasks.models import Task, TaskProject
from momentum.domain.tasks.schemas import (
    BlockedTaskOut,
    DependenciesOut,
    DependencyIn,
    FollowerIn,
    FollowersOut,
    NamedRef,
    OtherPlacementOut,
    ProjectRef,
    SubtaskCreateIn,
    SubtaskMoveIn,
    TaskBatchCreateIn,
    TaskBulkIn,
    TaskCreateIn,
    TaskDetailOut,
    TaskMoveIn,
    TaskOut,
    TaskPatchIn,
    TaskProjectAddIn,
    TaskProjectOut,
    TaskSummaryOut,
)

router = APIRouter(tags=["tasks"])


def task_out(t: Task, p: TaskProject | None, counts: tuple[int, int] | None = None) -> TaskOut:
    """API shape of a task. Subtasks have no section; their position is among siblings."""
    sub = t.parent_id is not None
    return TaskOut(
        id=t.id,
        number=t.number,
        key=task_key(t.number),
        title=t.title,
        type=t.type,
        project_id=p.project_id if p else None,
        section_id=None if sub or not p else p.section_id,
        position=t.parent_position if sub else (p.position if p else None),
        assignee_id=t.assignee_id,
        start_on=t.start_on,
        due_on=t.due_on,
        due_at=t.due_at,
        completed_at=t.completed_at,
        parent_id=t.parent_id,
        priority=t.priority,
        version=t.version,
        created_at=t.created_at,
        subtask_count=counts[0] if counts else 0,
        completed_subtask_count=counts[1] if counts else 0,
    )


@router.get(
    "/projects/{project_id}/tasks",
    response_model=ListOut[TaskOut],
    summary="Top-level tasks of a project (incomplete in order, or completed paged)",
)
async def list_tasks(
    project_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    completed: bool = Query(default=False),
    before: datetime | None = Query(default=None, description="Completed-at cursor"),
    assignee: list[str] = Query(
        default=[],
        max_length=50,
        description='User ids, "me" or "none" (unassigned); several are OR-ed',
    ),
    due: service.DueFilter = Query(default="any"),
    sort: service.TaskSort = Query(default="manual"),
) -> ListOut[TaskOut]:
    for a in assignee:
        if a not in ("me", "none"):
            try:
                uuid.UUID(a)
            except ValueError:
                raise ValidationFailed(f"Invalid assignee filter: {a[:40]}") from None
    async with uow.transaction() as s:
        rows = await service.list_project_tasks(
            s,
            ctx,
            project_id,
            completed=completed,
            before=before,
            assignees=assignee,
            due=due,
            sort=sort,
        )
        counts = await service.subtask_counts(s, [t.id for t, _ in rows])
        return ListOut(data=[task_out(t, p, counts.get(t.id)) for t, p in rows])


@router.post(
    "/projects/{project_id}/tasks",
    response_model=MutationOut[TaskOut],
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
)
async def create_task(
    project_id: uuid.UUID, body: TaskCreateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.create_task(
            s,
            ctx,
            project_id,
            body.title,
            section_id=body.section_id,
            after_id=body.after_id,
            before_id=body.before_id,
            assignee_id=body.assignee_id,
            due_on=body.due_on,
            due_at=body.due_at,
        )
        t, p = m.entity
        return MutationOut(
            data=task_out(t, p), meta=MutationMeta(activity_id=m.activity_id, version=m.version)
        )


@router.post(
    "/projects/{project_id}/tasks/batch",
    response_model=MutationOut[ListOut[TaskOut]],
    status_code=status.HTTP_201_CREATED,
    summary="Create several tasks in order (one undoable batch)",
)
async def create_tasks(
    project_id: uuid.UUID, body: TaskBatchCreateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[ListOut[TaskOut]]:
    async with uow.transaction() as s:
        m = await service.create_tasks(
            s, ctx, project_id, body.titles, section_id=body.section_id, after_id=body.after_id
        )
        return MutationOut(
            data=ListOut(data=[task_out(t, p) for t, p in m.entity]),
            meta=MutationMeta(batch_id=m.batch_id),
        )


async def detail_out(
    s: AsyncSession, t: Task, p: TaskProject | None, role: str | None = None
) -> TaskDetailOut:
    project = await s.get(Project, p.project_id) if p else None
    section = await s.get(Section, p.section_id) if p and t.parent_id is None else None
    parent = await s.get(Task, t.parent_id) if t.parent_id else None
    counts = (await service.subtask_counts(s, [t.id])).get(t.id)
    return TaskDetailOut(
        **task_out(t, p, counts).model_dump(),
        parent=NamedRef(id=parent.id, name=parent.title) if parent else None,
        followers=await service.list_followers(s, t.id),
        my_role=role,
        description=t.description,
        description_hash=doc_hash(t.description),
        project=ProjectRef(id=project.id, name=project.name, color=project.color)
        if project
        else None,
        section=NamedRef(id=section.id, name=section.name) if section else None,
        created_by=t.created_by,
        completed_by=t.completed_by,
        updated_at=t.updated_at,
    )


@router.get("/tasks/{task_id}", response_model=TaskDetailOut, summary="A task with details")
async def get_task(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> TaskDetailOut:
    async with uow.transaction() as s:
        t, p, role = await service.get_task(s, ctx, task_id)
        return await detail_out(s, t, p, role)


@router.patch("/tasks/{task_id}", response_model=MutationOut[TaskDetailOut], summary="Edit a task")
async def patch_task(
    task_id: uuid.UUID,
    body: TaskPatchIn,
    ctx: CtxDep,
    uow: UowDep,
    if_match: int | None = Header(default=None),
) -> MutationOut[TaskDetailOut]:
    async with uow.transaction() as s:
        m = await service.update_task(
            s, ctx, task_id, body.model_dump(exclude_unset=True), expected_version=if_match
        )
        _, p, role = await service.get_task(s, ctx, task_id)
        await s.flush()
        await s.refresh(m.entity, ["updated_at"])
        return MutationOut(
            data=await detail_out(s, m.entity, p, role),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )


async def _complete(
    task_id: uuid.UUID, ctx: CtxDep, uow: UowDep, flag: bool, *, force: bool = False
) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.set_completed(s, ctx, task_id, flag, force=force)
        _, p, _ = await service.get_task(s, ctx, task_id)
        return MutationOut(
            data=task_out(m.entity, p),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )


@router.post("/tasks/{task_id}/complete", response_model=MutationOut[TaskOut], summary="Complete")
async def complete(
    task_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    force: bool = Query(
        default=False, description="Complete even if this task has incomplete blockers"
    ),
) -> MutationOut[TaskOut]:
    return await _complete(task_id, ctx, uow, True, force=force)


@router.post(
    "/tasks/{task_id}/uncomplete", response_model=MutationOut[TaskOut], summary="Mark incomplete"
)
async def uncomplete(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[TaskOut]:
    return await _complete(task_id, ctx, uow, False)


@router.delete("/tasks/{task_id}", response_model=MutationOut[OkOut], summary="Delete (soft)")
async def delete_task(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.delete_task(s, ctx, task_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.post(
    "/tasks/{task_id}/move",
    response_model=MutationOut[TaskOut],
    summary="Move a task to a slot in a section of its project",
)
async def move_task(
    task_id: uuid.UUID, body: TaskMoveIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.move_tasks(
            s,
            ctx,
            [task_id],
            section_id=body.section_id,
            after_id=body.after_id,
            before_id=body.before_id,
        )
        t, p = m.entity[0]
        return MutationOut(
            data=task_out(t, p), meta=MutationMeta(activity_id=m.activity_id, version=t.version)
        )


@router.post(
    "/tasks/bulk",
    response_model=MutationOut[ListOut[TaskOut]],
    summary="Apply one action to many tasks (all-or-nothing, one undo batch)",
)
async def bulk_tasks(body: TaskBulkIn, ctx: CtxDep, uow: UowDep) -> MutationOut[ListOut[TaskOut]]:
    async with uow.transaction() as s:
        m = await service.bulk(
            s,
            ctx,
            body.task_ids,
            body.action,
            patch=body.patch.model_dump(exclude_unset=True) if body.patch else None,
            section_id=body.section_id,
            after_id=body.after_id,
            before_id=body.before_id,
        )
        placements = await service.placements_for(s, [t.id for t in m.entity])
        return MutationOut(
            data=ListOut(data=[task_out(t, placements.get(t.id)) for t in m.entity]),
            meta=MutationMeta(batch_id=m.batch_id),
        )


@router.get("/tasks/{task_id}/subtasks", response_model=ListOut[TaskOut], summary="Subtasks")
async def list_subtasks(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> ListOut[TaskOut]:
    async with uow.transaction() as s:
        children = await service.list_subtasks(s, ctx, task_id)
        _, p, _ = await service.get_task(s, ctx, task_id)
        counts = await service.subtask_counts(s, [c.id for c in children])
        return ListOut(data=[task_out(c, p, counts.get(c.id)) for c in children])


@router.post(
    "/tasks/{task_id}/subtasks",
    response_model=MutationOut[TaskOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add a subtask",
)
async def create_subtask(
    task_id: uuid.UUID, body: SubtaskCreateIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.create_subtask(
            s, ctx, task_id, body.title, after_id=body.after_id, before_id=body.before_id
        )
        _, p, _ = await service.get_task(s, ctx, m.entity.id)
        return MutationOut(
            data=task_out(m.entity, p),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )


@router.post(
    "/tasks/{task_id}/subtask-move",
    response_model=MutationOut[TaskOut],
    summary="Reorder a subtask among its siblings",
)
async def move_subtask(
    task_id: uuid.UUID, body: SubtaskMoveIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.move_subtask(
            s, ctx, task_id, after_id=body.after_id, before_id=body.before_id
        )
        _, p, _ = await service.get_task(s, ctx, task_id)
        return MutationOut(
            data=task_out(m.entity, p),
            meta=MutationMeta(activity_id=m.activity_id, version=m.version),
        )


@router.post(
    "/tasks/{task_id}/outdent",
    response_model=MutationOut[TaskOut],
    summary="Move a subtask up one level (to its grandparent, or into the parent's section)",
)
async def outdent_subtask(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> MutationOut[TaskOut]:
    async with uow.transaction() as s:
        m = await service.outdent_subtask(s, ctx, task_id)
        t, _ = m.entity
        _, p, _ = await service.get_task(s, ctx, task_id)
        return MutationOut(
            data=task_out(t, p), meta=MutationMeta(activity_id=m.activity_id, version=m.version)
        )


@router.post(
    "/tasks/{task_id}/followers",
    response_model=MutationOut[FollowersOut],
    summary="Follow a task (yourself, or add someone as a collaborator)",
)
async def add_follower(
    task_id: uuid.UUID, body: FollowerIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[FollowersOut]:
    async with uow.transaction() as s:
        m = await service.set_following(s, ctx, task_id, body.user_id, True)
        return MutationOut(
            data=FollowersOut(followers=m.entity), meta=MutationMeta(activity_id=m.activity_id)
        )


@router.delete(
    "/tasks/{task_id}/followers/{user_id}",
    response_model=MutationOut[FollowersOut],
    summary="Stop following (yourself, or remove a collaborator)",
)
async def remove_follower(
    task_id: uuid.UUID, user_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[FollowersOut]:
    async with uow.transaction() as s:
        m = await service.set_following(s, ctx, task_id, user_id, False)
        return MutationOut(
            data=FollowersOut(followers=m.entity), meta=MutationMeta(activity_id=m.activity_id)
        )


@router.get(
    "/tasks/{task_id}/projects",
    response_model=ListOut[TaskProjectOut],
    summary="Every project this task is placed in (S2.4.1 multi-homing)",
)
async def list_task_projects(
    task_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[TaskProjectOut]:
    async with uow.transaction() as s:
        rows = await service.list_task_projects(s, ctx, task_id)
        return ListOut(
            data=[
                TaskProjectOut(
                    project=ProjectRef(id=p.id, name=p.name, color=p.color),
                    section=NamedRef(id=sec.id, name=sec.name),
                    position=tp.position,
                )
                for tp, p, sec in rows
            ]
        )


@router.get(
    "/projects/{project_id}/other-placements",
    response_model=ListOut[OtherPlacementOut],
    summary="Every other project each of this project's tasks is also placed in, in one call",
)
async def list_other_placements(
    project_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[OtherPlacementOut]:
    async with uow.transaction() as s:
        rows = await service.list_other_placements(s, ctx, project_id)
        return ListOut(
            data=[
                OtherPlacementOut(
                    task_id=task_id, project=ProjectRef(id=p.id, name=p.name, color=p.color)
                )
                for task_id, p in rows
            ]
        )


@router.post(
    "/tasks/{task_id}/projects",
    response_model=MutationOut[TaskProjectOut],
    status_code=status.HTTP_201_CREATED,
    summary="Add a task to another project (multi-homing)",
)
async def add_task_to_project(
    task_id: uuid.UUID, body: TaskProjectAddIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TaskProjectOut]:
    async with uow.transaction() as s:
        m = await service.add_task_to_project(
            s,
            ctx,
            task_id,
            body.project_id,
            section_id=body.section_id,
            after_id=body.after_id,
            before_id=body.before_id,
        )
        tp, p, sec = m.entity
        return MutationOut(
            data=TaskProjectOut(
                project=ProjectRef(id=p.id, name=p.name, color=p.color),
                section=NamedRef(id=sec.id, name=sec.name),
                position=tp.position,
            ),
            meta=MutationMeta(activity_id=m.activity_id),
        )


@router.delete(
    "/tasks/{task_id}/projects/{project_id}",
    response_model=MutationOut[OkOut],
    summary="Remove a task from one project (it must stay in at least one other)",
)
async def remove_task_from_project(
    task_id: uuid.UUID, project_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.remove_task_from_project(s, ctx, task_id, project_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


def _summary(t: Task) -> TaskSummaryOut:
    return TaskSummaryOut(
        id=t.id, key=task_key(t.number), title=t.title, completed_at=t.completed_at
    )


@router.get(
    "/tasks/{task_id}/dependencies",
    response_model=DependenciesOut,
    summary="Tasks this one is blocked by, and tasks blocked by this one",
)
async def get_dependencies(task_id: uuid.UUID, ctx: CtxDep, uow: UowDep) -> DependenciesOut:
    async with uow.transaction() as s:
        blocked_by, blocking = await service.list_dependencies(s, ctx, task_id)
        return DependenciesOut(
            blocked_by=[_summary(t) for t in blocked_by], blocking=[_summary(t) for t in blocking]
        )


@router.post(
    "/tasks/{task_id}/dependencies",
    response_model=MutationOut[TaskSummaryOut],
    status_code=status.HTTP_201_CREATED,
    summary="Block this task on another completing first",
)
async def add_dependency(
    task_id: uuid.UUID, body: DependencyIn, ctx: CtxDep, uow: UowDep
) -> MutationOut[TaskSummaryOut]:
    async with uow.transaction() as s:
        m = await service.add_dependency(s, ctx, task_id, body.depends_on_id)
        return MutationOut(data=_summary(m.entity), meta=MutationMeta(activity_id=m.activity_id))


@router.delete(
    "/tasks/{task_id}/dependencies/{depends_on_id}",
    response_model=MutationOut[OkOut],
    summary="Remove a dependency",
)
async def remove_dependency(
    task_id: uuid.UUID, depends_on_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> MutationOut[OkOut]:
    async with uow.transaction() as s:
        m = await service.remove_dependency(s, ctx, task_id, depends_on_id)
    return MutationOut(data=OkOut(), meta=MutationMeta(activity_id=m.activity_id))


@router.get(
    "/projects/{project_id}/tasks/search",
    response_model=ListOut[TaskSummaryOut],
    summary="Find a task in this project (for the 'add a blocker' picker)",
)
async def search_project_tasks(
    project_id: uuid.UUID,
    ctx: CtxDep,
    uow: UowDep,
    q: str = Query(default=""),
    exclude: uuid.UUID | None = Query(default=None),
) -> ListOut[TaskSummaryOut]:
    async with uow.transaction() as s:
        rows = await service.search_project_tasks(s, ctx, project_id, q, exclude=exclude)
        return ListOut(data=[_summary(t) for t in rows])


@router.get(
    "/projects/{project_id}/blocked-tasks",
    response_model=ListOut[BlockedTaskOut],
    summary="Task ids in this project with at least one incomplete blocker",
)
async def list_blocked_tasks(
    project_id: uuid.UUID, ctx: CtxDep, uow: UowDep
) -> ListOut[BlockedTaskOut]:
    async with uow.transaction() as s:
        ids = await service.list_blocked_tasks(s, ctx, project_id)
        return ListOut(data=[BlockedTaskOut(task_id=i) for i in ids])
