# Coding Standards

## 1. General

- Readability over cleverness. Small functions, explicit names, no magic.
- Comments explain **why**, not what. Public functions/classes get docstrings (backend) or TSDoc (frontend) when their behavior isn't obvious from the signature.
- Nulls are preserved and handled explicitly, never replaced with fabricated values.
- No TODOs without an owner and a slice/issue reference: `# TODO(S2.4.3): …`.
- Don't reformat unrelated code in a slice.

## 2. Backend (Python 3.12)

**Tooling:** `uv` (deps + venv), `ruff` (lint + format, line length 100), `mypy --strict` for `momentum/`, `import-linter` for the layering rules, `pytest`.

**Naming:** modules `snake_case`; classes `PascalCase`; Pydantic schemas `TaskOut`, `TaskCreateIn`, `TaskPatchIn`; services are verbs: `create_task`, `update_task`, `move_task`, `list_project_tasks`.

**Module template (`domain/<module>/`)**

```python
# models.py
class Task(Base, TimestampMixin, SoftDeleteMixin, WorkspaceMixin):
    __tablename__ = "tasks"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    number: Mapped[int]
    title: Mapped[str] = mapped_column(String(500))
    ...

# schemas.py
class TaskPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=UNSET, max_length=500)   # UNSET sentinel distinguishes "absent" from null
    ...

# service.py
async def update_task(ctx: Ctx, uow: UnitOfWork, task_id: UUID, patch: TaskPatchIn,
                      expected_version: int | None = None) -> Mutation[Task]:
    task = await _get_for_update(uow, ctx, task_id)
    require(ctx, "task.edit", task)
    changes = apply_patch(task, patch)                      # returns {field: (old, new)}
    if not changes:
        return Mutation(task, activity_id=None)
    check_version(task, expected_version)
    task.version += 1
    act = await record_activity(uow, ctx, task, "task.updated", changes,
                                undo=UndoOp("tasks.update", {"id": task.id, "patch": inverse(changes)}))
    await emit(uow, ctx, EventType.TASK_UPDATED, task, {"changes": changes, "version": task.version}, act)
    return Mutation(task, activity_id=act.id)

# router.py
@router.patch("/tasks/{task_id}", response_model=MutationOut[TaskOut], responses=ERRORS_404_403_409_422)
async def patch_task(task_id: UUID, body: TaskPatchIn, ctx: Ctx = Depends(get_ctx),
                     uow: UnitOfWork = Depends(get_uow), if_match: int | None = Header(None)):
    m = await service.update_task(ctx, uow, task_id, body, expected_version=if_match)
    return MutationOut.of(m, TaskOut)

# tools.py (AI exposure)
@tool(name="update_task", risk="low", description="…")
async def update_task_tool(ctx: Ctx, uow: UnitOfWork, task: TaskRef, patch: TaskPatchIn) -> ToolResult:
    t = await resolve_task_ref(ctx, uow, task)
    m = await service.update_task(ctx, uow, t.id, patch)
    return ToolResult.changed(m)
```

**Rules**
- Async all the way (SQLAlchemy async sessions). No sync DB calls in request paths.
- Queries that return lists always apply `visible_*_clause(ctx)` and `deleted_at is null`.
- No N+1s: use `selectinload`/explicit joins. Tests for list endpoints assert the query count (`assert_max_queries(n)` fixture).
- Time: always timezone-aware UTC in the DB. Convert to the user timezone only for "today/this week" logic (helper `user_today(ctx)`).
- Money/costs: `Decimal`.
- Logging: `structlog.get_logger("momentum.<module>")`, with key-value context (`task_id=…`). No f-string log messages with user content at INFO.
- Settings are accessed via `ctx.settings` or dependency injection, never by importing a global.

**Migrations**
- One Alembic revision per slice that changes schema. Name it `sNNNN_<slice>_<desc>`.
- Always review autogenerate output; add `CHECK` constraints and indexes explicitly.
- Data migrations are separate revisions and idempotent.
- Destructive changes (drop/rename column) → expand/contract across two slices, with human approval.

## 3. Frontend (TypeScript strict)

**Tooling:** ESLint (typescript-eslint strict, react-hooks, jsx-a11y, import/order, no-restricted-imports for layering), Prettier, `tsc --noEmit`, Vitest.

**Naming:** components `PascalCase.tsx`; hooks `useThing.ts`; feature API files `api.ts`, query hooks in `queries.ts`; test files next to source `Thing.test.tsx`.

**Rules**
- Features may import from `components/`, `lib/`, `stores/` and from **other features only via their `index.ts`**.
- `components/ui` never imports from `features/`.
- Server data only through TanStack Query hooks; no `fetch` in components.
- Styling: Tailwind utilities that map to tokens; `cn()` helper for conditional classes; no inline hex/oklch; `style={{}}` only for dynamic geometry (virtual rows, drag transforms, bars).
- Every interactive element: accessible name, focus state, keyboard support.
- Every data-driven component handles loading/empty/error explicitly.
- AI-authored content must render through `AICallout`/`AIBadge` (lint rule: `created_via === 'ai'|'agent'` values must be passed to a component that shows the badge; enforced in review).
- Dates via `lib/dates.ts` helpers only (`formatDue`, `parseNaturalDate`, `isOverdue`), always user-timezone aware.

**Component template**

```tsx
type TaskRowProps = { taskId: string; projectId: string; index: number };

export const TaskRow = memo(function TaskRow({ taskId, projectId }: TaskRowProps) {
  const task = useTaskFromList(projectId, taskId);          // selector over the cached list
  const update = useUpdateTask();
  const isSelected = useSelection((s) => s.ids.has(taskId));
  if (!task) return null;
  return (
    <div role="row" aria-selected={isSelected} className={cn('row', isSelected && 'bg-selection')}>
      <CompleteCheck checked={!!task.completed_at} onChange={() => update.mutate({ id: taskId, patch: { completed: !task.completed_at } })} />
      <InlineText value={task.title} onCommit={(title) => update.mutate({ id: taskId, patch: { title } })} aria-label="Task name" />
      {/* … */}
    </div>
  );
});
```

## 4. Git and commits (for the human pushing)

- Branch per slice: `s1.2.3-inline-dates`.
- Commit message: `S1.2.3: inline assignee and due date editing` + body bullets (what, why, notes). The AI proposes the message in its slice report.
- Never commit `.env`, data dumps, or real company data.

## 5. Dependencies

- Backend runtime deps pinned via `uv.lock`; frontend via `pnpm-lock.yaml` (pnpm recommended).
- Adding a dependency: justify it in the slice report; architectural ones need an ADR. Prefer well-maintained, permissively licensed (MIT/Apache/BSD) packages.
