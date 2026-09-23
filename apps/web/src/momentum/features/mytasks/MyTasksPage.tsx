import {
  closestCenter,
  DndContext,
  DragOverlay,
  pointerWithin,
  PointerSensor,
  useDndContext,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragMoveEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { CheckCircle2, ChevronDown, ChevronRight, ListChecks } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import {
  dropNeighbors,
  emptySelection,
  step,
  TaskNavProvider,
  TaskPane,
  TaskRow,
  useTaskNav,
  type DropPlacement,
  type Selection,
  type Task,
  type TaskPatch,
} from '@/features/tasks';
import { cn } from '@/lib/cn';
import { formatDue } from '@/lib/dates';
import { BUCKETS, useMyTaskMutations, useMyTasks, type Bucket, type MyTask } from './queries';

type Drop = { bucket: Bucket; anchorId: string | null; placement: DropPlacement };
const COLLAPSE_KEY = 'momentum.mytasks.collapsed';

/** My Tasks: everything assigned to me, in personal buckets (ux-specs §3). */
export function MyTasksPage() {
  return (
    <TaskNavProvider>
      <MyTasksBody />
    </TaskNavProvider>
  );
}

function MyTasksBody() {
  const nav = useTaskNav()!;
  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-auto px-8 py-6">
        <h1 className="page-title mb-4 flex items-center gap-2">
          <Icon icon={ListChecks} size={20} /> My Tasks
        </h1>
        <MyTasksList />
      </div>
      {nav.openId ? (
        <TaskPane
          taskId={nav.openId}
          onClose={nav.close}
          onStep={nav.step}
          onOpenTask={(id) => nav.open(id)}
        />
      ) : null}
    </div>
  );
}

const collisions: CollisionDetection = (args) => {
  const within = pointerWithin(args);
  return within.length ? within : closestCenter(args);
};

function MyTasksList() {
  const [showCompleted, setShowCompleted] = useState(false);
  const open = useMyTasks(false);
  const done = useMyTasks(true, showCompleted);
  const m = useMyTaskMutations();
  const nav = useTaskNav();
  const meId = useMe().data?.user.id;
  const container = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(COLLAPSE_KEY) ?? '[]') as string[]);
    } catch {
      return new Set();
    }
  });
  const [fading, setFading] = useState<ReadonlySet<string>>(new Set());
  const [selection, setSelection] = useState<Selection>(emptySelection);
  const [drag, setDrag] = useState<MyTask | null>(null);
  const [drop, setDropState] = useState<Drop | null>(null);
  const dropRef = useRef<Drop | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const byBucket = useMemo(() => {
    const map = new Map<Bucket, MyTask[]>(BUCKETS.map((b) => [b.id, []]));
    for (const t of open.data ?? []) {
      if (t.completed_at && !fading.has(t.id)) continue;
      map.get(t.bucket ?? 'later')?.push(t);
    }
    return map;
  }, [open.data, fading]);
  const order = useMemo(
    () =>
      BUCKETS.filter((b) => !collapsed.has(b.id)).flatMap((b) => (byBucket.get(b.id) ?? []).map((t) => t.id)),
    [byBucket, collapsed],
  );
  useEffect(() => nav?.setOrder(order), [nav, order]);

  const toggleBucket = (id: string) =>
    setCollapsed((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      try {
        localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...n]));
      } catch {
        /* ignore */
      }
      return n;
    });

  const onToggle = useCallback(
    (t: Task) => {
      const completing = !t.completed_at;
      m.setCompleted.mutate({ id: t.id, completed: completing });
      if (completing) {
        setFading((s) => new Set(s).add(t.id));
        setTimeout(() => setFading((s) => new Set([...s].filter((x) => x !== t.id))), 1500);
      }
    },
    [m.setCompleted],
  );
  const onRename = useCallback(
    (t: Task, title: string) => m.update.mutate({ id: t.id, patch: { title } }),
    [m.update],
  );
  const onUpdate = useCallback(
    (t: Task, patch: TaskPatch, message?: string) => m.update.mutate({ id: t.id, patch, message }),
    [m.update],
  );
  const onDelete = useCallback((t: Task) => m.remove.mutate(t.id), [m.remove]);
  const onOpen = useCallback((t: Task) => (nav?.openId === t.id ? nav.close() : nav?.open(t.id)), [nav]);
  const onFocusRow = useCallback(
    (t: Task) => setSelection((s) => (s.focus === t.id ? s : { ...s, focus: t.id })),
    [],
  );
  const onSelectClick = useCallback(
    (t: Task) => setSelection({ selected: new Set(), anchor: t.id, focus: t.id }),
    [],
  );

  const setDrop = (d: Drop | null) => {
    const p = dropRef.current;
    if (p?.bucket === d?.bucket && p?.anchorId === d?.anchorId && p?.placement === d?.placement) return;
    dropRef.current = d;
    setDropState(d);
  };
  const moveTo = (
    t: MyTask,
    bucket: Bucket,
    anchorId: string | null,
    placement: DropPlacement,
    message?: string,
  ) => {
    const bucketOrder = (byBucket.get(bucket) ?? []).map((x) => x.id);
    const n = dropNeighbors(bucketOrder, [t.id], anchorId, placement);
    if (!n) return;
    m.move.mutate({ id: t.id, bucket, ...n, message });
  };

  /** ⌘↑ / ⌘↓: move one step, crossing into the neighboring bucket at the edges. */
  const nudge = (t: MyTask, dir: 1 | -1) => {
    const bucket = t.bucket ?? 'later';
    const ids = (byBucket.get(bucket) ?? []).map((x) => x.id);
    const i = ids.indexOf(t.id);
    const neighbor = ids[i + dir];
    if (neighbor) moveTo(t, bucket, neighbor, dir === 1 ? 'after' : 'before');
    else {
      const bi = BUCKETS.findIndex((b) => b.id === bucket);
      const target = BUCKETS[bi + dir];
      if (!target) return;
      const others = byBucket.get(target.id) ?? [];
      const anchor = dir === 1 ? others[0] : others[others.length - 1];
      moveTo(t, target.id, anchor?.id ?? null, dir === 1 ? 'before' : 'after', `Moved to ${target.name}`);
    }
    requestAnimationFrame(() =>
      container.current?.querySelector<HTMLElement>(`[data-task-id="${CSS.escape(t.id)}"]`)?.focus(),
    );
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.dataset?.taskId === undefined) return;
    const k = e.key;
    const mod = e.metaKey || e.ctrlKey;
    if ((k === 'ArrowDown' || k === 'ArrowUp') && mod) {
      const t = (open.data ?? []).find((x) => x.id === target.dataset.taskId);
      if (t && !t.completed_at) nudge(t, k === 'ArrowDown' ? 1 : -1);
      e.preventDefault();
    } else if (k === 'ArrowDown' || k === 'ArrowUp' || (!mod && (k === 'j' || k === 'k'))) {
      const next = step(selection, k === 'ArrowDown' || k === 'j' ? 1 : -1, false, order);
      setSelection(next);
      const el = container.current?.querySelector<HTMLElement>(
        `[data-task-id="${CSS.escape(next.focus ?? '')}"]`,
      );
      el?.focus();
      el?.scrollIntoView?.({ block: 'nearest' });
      if (nav?.openId && next.focus) nav.open(next.focus, { replace: true });
      e.preventDefault();
    } else if (mod && k === 'Enter') {
      const t = (open.data ?? []).find((x) => x.id === target.dataset.taskId);
      if (t) onToggle(t);
      e.preventDefault();
    }
  };

  if (open.isPending) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-8" />
        ))}
      </div>
    );
  }
  if (open.isError) return <ErrorState error={open.error} onRetry={() => void open.refetch()} />;
  const total = (open.data ?? []).filter((t) => !t.completed_at).length;

  const row = (t: MyTask, drop_: Drop | null, draggable = true) => (
    <TaskRow
      task={t}
      canEdit
      draggable={draggable}
      fading={fading.has(t.id)}
      meId={meId}
      hideAssignee
      project={t.project}
      dragging={drag?.id === t.id}
      dropIndicator={drop_?.anchorId === t.id ? drop_.placement : null}
      isOpen={nav?.openId === t.id}
      onOpen={onOpen}
      onFocusRow={onFocusRow}
      onSelectClick={onSelectClick}
      onUpdate={onUpdate}
      onToggle={onToggle}
      onRename={onRename}
      onEnter={() => undefined}
      onDelete={onDelete}
    />
  );

  return (
    // Keyboard handling is delegated from the rows (each row is focusable).
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div ref={container} className="@container" onKeyDown={onKeyDown}>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-muted">
          {total ? `${total} open task${total === 1 ? '' : 's'} assigned to you` : null}
        </p>
        <Button
          size="sm"
          variant="text"
          aria-pressed={showCompleted}
          onClick={() => setShowCompleted(!showCompleted)}
        >
          <Icon icon={CheckCircle2} /> {showCompleted ? 'Hide completed' : 'Show completed'}
        </Button>
      </div>
      {total === 0 && !showCompleted ? (
        <EmptyState icon={ListChecks} title="Nothing assigned to you">
          Tasks people assign to you show up here, sorted by when they're due.
        </EmptyState>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={collisions}
          onDragStart={(e: DragStartEvent) =>
            setDrag((open.data ?? []).find((t) => t.id === String(e.active.id)) ?? null)
          }
          onDragMove={(e: DragMoveEvent) => {
            const data = e.over?.data.current as
              { kind?: string; taskId?: string; sectionId?: string } | undefined;
            if (data?.kind === 'section-end' && data.sectionId)
              return setDrop({ bucket: data.sectionId as Bucket, anchorId: null, placement: 'after' });
            if (data?.kind === 'task' && data.taskId && e.over) {
              const over = (open.data ?? []).find((t) => t.id === data.taskId);
              const r = e.active.rect.current.translated;
              const mid = r ? r.top + r.height / 2 : 0;
              if (over?.bucket)
                return setDrop({
                  bucket: over.bucket,
                  anchorId: over.id,
                  placement: mid < e.over.rect.top + e.over.rect.height / 2 ? 'before' : 'after',
                });
            }
            setDrop(null);
          }}
          onDragEnd={() => {
            const d = dropRef.current;
            if (drag && d) {
              const name = BUCKETS.find((b) => b.id === d.bucket)?.name;
              moveTo(
                drag,
                d.bucket,
                d.anchorId,
                d.placement,
                drag.bucket !== d.bucket ? `Moved to ${name}` : undefined,
              );
            }
            setDrag(null);
            setDrop(null);
          }}
          onDragCancel={() => {
            setDrag(null);
            setDrop(null);
          }}
        >
          {BUCKETS.map((b) => {
            const tasks = byBucket.get(b.id) ?? [];
            const isCollapsed = collapsed.has(b.id);
            return (
              <section key={b.id} aria-label={b.name} className="mb-3">
                <BucketHeader bucket={b.id} active={drop?.bucket === b.id && !drop.anchorId && isCollapsed}>
                  <button
                    type="button"
                    onClick={() => toggleBucket(b.id)}
                    aria-expanded={!isCollapsed}
                    aria-label={isCollapsed ? `Expand ${b.name}` : `Collapse ${b.name}`}
                    className="grid h-7 w-6 place-items-center rounded text-muted hover:text-ink"
                  >
                    <Icon icon={isCollapsed ? ChevronRight : ChevronDown} size={15} />
                  </button>
                  <h2 className="text-[15px] font-semibold">{b.name}</h2>
                  <span className="tabular text-xs text-muted">{tasks.length}</span>
                </BucketHeader>
                {isCollapsed ? null : (
                  <div role="list" aria-label={`Tasks in ${b.name}`} className="pl-7">
                    {tasks.map((t) => (
                      <div key={t.id}>{row(t, drop)}</div>
                    ))}
                    <BucketEnd bucket={b.id} active={drop?.bucket === b.id && !drop.anchorId}>
                      {tasks.length === 0 ? (
                        <p className="py-1.5 text-xs text-muted-2">Drag tasks here</p>
                      ) : null}
                    </BucketEnd>
                  </div>
                )}
              </section>
            );
          })}
          <DragOverlay dropAnimation={null}>
            {drag ? (
              <div className="flex h-9 max-w-md items-center gap-2 rounded-md bg-surface px-3 text-[13.5px] shadow-pop">
                <span className="truncate">{drag.title}</span>
                {drag.due_on ? (
                  <span className="text-xs text-muted">{formatDue(drag.due_on, drag.due_at)}</span>
                ) : null}
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      )}
      {showCompleted ? (
        <section aria-label="Completed" className="mt-4">
          <h2 className="mb-1 pl-7 text-[15px] font-semibold">Completed</h2>
          <div role="list" aria-label="Completed tasks" className="pl-7">
            {done.isPending ? <Skeleton className="h-8" /> : null}
            {(done.data ?? []).map((t) => (
              <div key={t.id}>{row(t, null, false)}</div>
            ))}
            {done.data && !done.data.length ? (
              <p className="py-1.5 text-xs text-muted-2">Nothing completed yet</p>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function BucketHeader({
  bucket,
  active,
  children,
}: {
  bucket: Bucket;
  active: boolean;
  children: ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `bucket-head:${bucket}`,
    data: { kind: 'section-end', sectionId: bucket },
  });
  const dragging = useDndContext().active !== null;
  return (
    <div
      ref={setNodeRef}
      className={cn(
        'flex h-9 items-center gap-1 rounded-md',
        dragging && (isOver || active) && 'bg-accent-tint ring-1 ring-focus',
      )}
    >
      {children}
    </div>
  );
}

function BucketEnd({ bucket, active, children }: { bucket: Bucket; active: boolean; children: ReactNode }) {
  const { setNodeRef } = useDroppable({
    id: `bucket-end:${bucket}`,
    data: { kind: 'section-end', sectionId: bucket },
  });
  const dragging = useDndContext().active !== null;
  return (
    <div ref={setNodeRef} className={cn('relative min-h-2', dragging && 'min-h-9')}>
      {active ? (
        <span aria-hidden className="absolute top-0 right-0 left-0 h-0.5 rounded-full bg-focus" />
      ) : null}
      {children}
    </div>
  );
}
