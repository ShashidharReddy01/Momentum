import {
  closestCenter,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  pointerWithin,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragMoveEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  horizontalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, MoreHorizontal, Plus, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { CompleteCheck } from '@/components/common/CompleteCheck';
import { DueText } from '@/components/common/DueText';
import { ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { InlineText } from '@/components/common/InlineText';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePeople, type Person } from '@/features/people';
import { useSectionMutations, useSections, type Section } from '@/features/sections';
import { applyRealtimeEvent, useChannel } from '@/lib/realtime';
import { cn } from '@/lib/cn';
import { useQueryClient } from '@tanstack/react-query';
import { dropNeighbors } from './selection';
import { useProjectTasks, useTaskMutations, type Task } from './queries';
import { useTaskNav } from './pane/nav';

type CardDrag = { kind: 'card'; task: Task; sectionId: string | null };
type Drop = { sectionId: string; anchorId: string | null; placement: 'before' | 'after' } | null;

const INTERACTIVE = 'button, input, textarea, a, [role="checkbox"]';

const isCard = (data: unknown): data is CardDrag =>
  !!data && typeof data === 'object' && (data as { kind?: string }).kind === 'card';

/** Board view (S2.2.1): columns = sections, cards = tasks. Drag cards within/across columns and
 * columns themselves; keyboard: arrows move focus, Enter opens the pane, ⌘←/→ moves the
 * focused card to the neighboring column. */
export function BoardView({
  projectId,
  canEdit,
  color,
}: {
  projectId: string;
  canEdit: boolean;
  color: string | null;
}) {
  const qc = useQueryClient();
  useChannel(`project:${projectId}`, (event) => applyRealtimeEvent(qc, event, { projectId }));
  const sections = useSections(projectId);
  const open = useProjectTasks(projectId);
  const people = usePeople().data;
  const {
    move: moveSection,
    create: createSection,
    rename: renameSection,
    remove: removeSection,
  } = useSectionMutations(projectId);
  const m = useTaskMutations(projectId);
  const nav = useTaskNav();
  const containerRef = useRef<HTMLDivElement>(null);
  const [focused, setFocused] = useState<string | null>(null);
  // The vertical slot a Left/Right move tries to land on, remembered across
  // columns of different heights (so bouncing back doesn't lose your place).
  const vIdxRef = useRef(0);
  const [drag, setDrag] = useState<CardDrag | null>(null);
  const [drop, setDropState] = useState<Drop>(null);
  const dropRef = useRef<Drop>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const peopleById = useMemo(() => new Map((people ?? []).map((p) => [p.id, p])), [people]);
  const bySection = useMemo(() => {
    const map = new Map<string, Task[]>();
    for (const t of open.data ?? []) {
      const list = map.get(t.section_id ?? '');
      if (list) list.push(t);
      else map.set(t.section_id ?? '', [t]);
    }
    for (const list of map.values()) list.sort((a, b) => ((a.position ?? '') < (b.position ?? '') ? -1 : 1));
    return map;
  }, [open.data]);
  // flat visual order for arrow-key navigation: column by column, top to bottom
  const flatOrder = useMemo(
    () => (sections.data ?? []).flatMap((s) => (bySection.get(s.id) ?? []).map((t) => t.id)),
    [sections.data, bySection],
  );
  useEffect(() => nav?.setOrder(flatOrder), [nav, flatOrder]);

  if (sections.isPending || open.isPending) {
    return (
      <div className="flex gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-80 w-72 shrink-0" />
        ))}
      </div>
    );
  }
  if (sections.isError) return <ErrorState error={sections.error} onRetry={() => void sections.refetch()} />;
  if (open.isError) return <ErrorState error={open.error} onRetry={() => void open.refetch()} />;
  const list = sections.data;

  const setDrop = (d: Drop) => {
    const p = dropRef.current;
    if (p?.sectionId === d?.sectionId && p?.anchorId === d?.anchorId && p?.placement === d?.placement) return;
    dropRef.current = d;
    setDropState(d);
  };

  const moveColumnTo = (id: string, newIndex: number) => {
    const reordered = arrayMove(
      list,
      list.findIndex((s) => s.id === id),
      newIndex,
    );
    const at = reordered.findIndex((s) => s.id === id);
    moveSection.mutate({
      id,
      afterId: reordered[at - 1]?.id ?? null,
      beforeId: reordered[at + 1]?.id ?? null,
    });
  };

  const moveCard = (
    task: Task,
    sectionId: string,
    anchorId: string | null,
    placement: 'before' | 'after',
  ) => {
    const order = (bySection.get(sectionId) ?? []).map((t) => t.id);
    const n = dropNeighbors(order, [task.id], anchorId, placement);
    if (!n) return;
    const crossing = task.section_id !== sectionId;
    m.move.mutate({
      ids: [task.id],
      sectionId,
      ...n,
      message: crossing ? `Moved to ${list.find((s) => s.id === sectionId)?.name}` : undefined,
    });
  };

  const moveFocusedToColumn = (dir: 1 | -1) => {
    if (!focused) return;
    const task = (open.data ?? []).find((t) => t.id === focused);
    if (!task) return;
    const i = list.findIndex((s) => s.id === task.section_id);
    const target = list[i + dir];
    if (!target) return;
    moveCard(task, target.id, null, 'after');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.dataset?.cardId === undefined) return;
    if ((e.metaKey || e.ctrlKey) && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      if (!canEdit) return;
      e.preventDefault();
      moveFocusedToColumn(e.key === 'ArrowRight' ? 1 : -1);
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const task = (open.data ?? []).find((t) => t.id === target.dataset.cardId);
    if (!task) return;
    if (e.key === 'Enter') {
      e.preventDefault();
      nav?.open(task.id);
      return;
    }
    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    e.preventDefault();
    const column = bySection.get(task.section_id ?? '') ?? [];
    const idx = column.findIndex((t) => t.id === task.id);
    let nextId: string | undefined;
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      nextId = column[idx + (e.key === 'ArrowDown' ? 1 : -1)]?.id;
      if (nextId) vIdxRef.current = idx + (e.key === 'ArrowDown' ? 1 : -1);
    } else {
      const si = list.findIndex((s) => s.id === task.section_id);
      const targetCol = list[si + (e.key === 'ArrowRight' ? 1 : -1)];
      if (targetCol) {
        const targetTasks = bySection.get(targetCol.id) ?? [];
        nextId = targetTasks[Math.min(vIdxRef.current, targetTasks.length - 1)]?.id ?? targetCol.id;
      }
    }
    if (nextId) {
      setFocused(nextId);
      containerRef.current?.querySelector<HTMLElement>(`[data-card-id="${CSS_escape(nextId)}"]`)?.focus();
    }
  };

  return (
    // Keyboard handling delegated from focusable cards.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div ref={containerRef} className="h-full" onKeyDown={onKeyDown}>
      <DndContext
        sensors={sensors}
        collisionDetection={collisions}
        onDragStart={(e: DragStartEvent) => {
          if (isCard(e.active.data.current)) setDrag(e.active.data.current);
        }}
        onDragMove={(e: DragMoveEvent) => {
          if (!drag) return;
          const data = e.over?.data.current as
            { kind?: string; taskId?: string; sectionId?: string } | undefined;
          if (!data) return setDrop(null);
          if (data.kind === 'column-end' && data.sectionId)
            return setDrop({ sectionId: data.sectionId, anchorId: null, placement: 'after' });
          if (data.kind === 'card' && data.taskId && data.sectionId && e.over) {
            const r = e.active.rect.current.translated;
            const mid = r ? r.top + r.height / 2 : 0;
            return setDrop({
              sectionId: data.sectionId,
              anchorId: data.taskId,
              placement: mid < e.over.rect.top + e.over.rect.height / 2 ? 'before' : 'after',
            });
          }
          setDrop(null);
        }}
        onDragEnd={(e: DragEndEvent) => {
          if (drag) {
            const d = dropRef.current;
            if (d) moveCard(drag.task, d.sectionId, d.anchorId, d.placement);
          } else if (e.over && e.active.id !== e.over.id) {
            moveColumnTo(
              String(e.active.id),
              list.findIndex((s) => s.id === e.over!.id),
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
        <SortableContext items={list.map((s) => s.id)} strategy={horizontalListSortingStrategy}>
          <div className="flex h-full items-start gap-3 overflow-x-auto pb-3">
            {list.map((s) => (
              <Column
                key={s.id}
                section={s}
                color={color}
                canEdit={canEdit}
                tasks={bySection.get(s.id) ?? []}
                peopleById={peopleById}
                focused={focused}
                dropActive={drop?.sectionId === s.id && !drop.anchorId}
                dragging={!!drag}
                onFocusCard={setFocused}
                onOpen={(id) => nav?.open(id)}
                onToggle={(t) => m.setCompleted.mutate({ id: t.id, completed: !t.completed_at })}
                onAddCard={(title) => m.create({ title, sectionId: s.id, afterId: null })}
                onRename={(name) => renameSection.mutate({ id: s.id, name })}
                onDelete={list.length > 1 && canEdit ? () => removeSection.mutate(s.id) : undefined}
              />
            ))}
            {canEdit ? <AddColumn onAdd={(name) => createSection.mutate({ name })} /> : null}
          </div>
        </SortableContext>
        <DragOverlay dropAnimation={null}>
          {drag ? (
            <div className="w-64 rounded-lg border border-hairline bg-surface p-2.5 text-[13.5px] shadow-pop">
              {drag.task.title}
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}

const CSS_escape = (s: string) => (window.CSS?.escape ? window.CSS.escape(s) : s);

function Column({
  section,
  color,
  canEdit,
  tasks,
  peopleById,
  focused,
  dropActive,
  dragging,
  onFocusCard,
  onOpen,
  onToggle,
  onAddCard,
  onRename,
  onDelete,
}: {
  section: Section;
  color: string | null;
  canEdit: boolean;
  tasks: Task[];
  peopleById: Map<string, Person>;
  focused: string | null;
  dropActive: boolean;
  dragging: boolean;
  onFocusCard: (id: string) => void;
  onOpen: (id: string) => void;
  onToggle: (t: Task) => void;
  onAddCard: (title: string) => void;
  onRename: (name: string) => void;
  onDelete?: () => void;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id: section.id, disabled: !canEdit, data: {} });
  const end = useDroppable({
    id: `col-end:${section.id}`,
    data: { kind: 'column-end', sectionId: section.id },
  });
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const t = title.trim();
    if (t) onAddCard(t);
    setTitle('');
    setAdding(false);
  };

  return (
    <section
      ref={setNodeRef}
      aria-label={`Column ${section.name}`}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        'flex h-full w-72 shrink-0 flex-col rounded-lg bg-surface-2/60',
        isDragging && 'relative z-10 shadow-pop',
      )}
    >
      <div className="flex items-center gap-1 px-2 pt-2 pb-1">
        {canEdit ? (
          <button
            ref={setActivatorNodeRef}
            type="button"
            aria-label={`Drag ${section.name}`}
            className="grid h-6 w-5 shrink-0 cursor-grab place-items-center text-muted-2 hover:text-ink"
            {...attributes}
            {...listeners}
          >
            <Icon icon={GripVertical} size={14} />
          </button>
        ) : null}
        <InlineText
          aria-label="Column name"
          value={section.name}
          disabled={!canEdit}
          onCommit={onRename}
          className="min-w-0 flex-1 text-[13.5px] font-semibold"
        />
        <span className="tabular text-xs text-muted-2">{tasks.length}</span>
        {onDelete ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton icon={MoreHorizontal} label={`${section.name} column actions`} size="icon-sm" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem className="text-crit" onSelect={onDelete}>
                <Icon icon={Trash2} /> Delete column
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
      <div
        role="list"
        aria-label={`Cards in ${section.name}`}
        className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto px-2"
      >
        {tasks.map((t) => (
          <Card
            key={t.id}
            task={t}
            color={color}
            assignee={t.assignee_id ? peopleById.get(t.assignee_id) : undefined}
            focused={focused === t.id}
            onFocus={() => onFocusCard(t.id)}
            onOpen={() => onOpen(t.id)}
            onToggle={() => onToggle(t)}
          />
        ))}
      </div>
      <div
        ref={end.setNodeRef}
        className={cn(
          'mx-2 mt-1 mb-2 rounded-md',
          dragging && 'min-h-8',
          dropActive && 'ring-1 ring-focus ring-inset',
        )}
      >
        {canEdit ? (
          adding ? (
            <form onSubmit={submit} className="px-0.5">
              <Input
                aria-label="New card title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onBlur={() => !title.trim() && setAdding(false)}
                onKeyDown={(e) => e.key === 'Escape' && (setAdding(false), setTitle(''))}
                placeholder="Task name"
                // eslint-disable-next-line jsx-a11y/no-autofocus -- user just asked to add a card
                autoFocus
              />
            </form>
          ) : (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="flex h-8 w-full items-center gap-1.5 rounded-md px-2 text-[13px] text-muted hover:bg-surface hover:text-ink"
            >
              <Icon icon={Plus} size={14} /> Add card
            </button>
          )
        ) : null}
      </div>
    </section>
  );
}

function Card({
  task,
  color,
  assignee,
  focused,
  onFocus,
  onOpen,
  onToggle,
}: {
  task: Task;
  color: string | null;
  assignee: Person | undefined;
  focused: boolean;
  onFocus: () => void;
  onOpen: () => void;
  onToggle: () => void;
}) {
  const drag = useDraggable({
    id: task.id,
    data: { kind: 'card', task, sectionId: task.section_id } satisfies CardDrag,
  });
  const drop = useDroppable({
    id: `card:${task.id}`,
    data: { kind: 'card', taskId: task.id, sectionId: task.section_id },
  });
  const done = !!task.completed_at;
  const subtasks = task.subtask_count > 0;

  return (
    // Keyboard handling (arrows, Enter, ⌘←/→) is delegated from BoardView's outer container,
    // like TaskRow's own list rows; the click here just opens the pane.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/click-events-have-key-events
    <div
      ref={(el) => {
        drag.setNodeRef(el);
        drop.setNodeRef(el);
      }}
      role="listitem"
      aria-label={task.title}
      data-card-id={task.id}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={focused ? 0 : -1}
      onFocus={onFocus}
      onClick={(e) => {
        if (!(e.target as HTMLElement).closest(INTERACTIVE)) onOpen();
      }}
      {...drag.listeners}
      className={cn(
        'group/card relative flex cursor-pointer flex-col gap-1.5 rounded-md border border-hairline bg-surface p-2.5 text-left outline-none',
        'hover:border-muted-2 focus-visible:shadow-[inset_0_0_0_2px_var(--focus)]',
        drag.isDragging && 'opacity-40',
      )}
    >
      {color ? (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 w-0.5 rounded-l-md"
          style={{ background: `var(--${color})` }}
        />
      ) : null}
      <div className="flex items-start gap-2">
        <CompleteCheck
          checked={done}
          label={done ? `Mark ${task.title} incomplete` : `Complete ${task.title}`}
          onChange={onToggle}
        />
        <span className={cn('min-w-0 flex-1 text-[13px] leading-snug', done && 'text-muted line-through')}>
          {task.title}
        </span>
      </div>
      <div className="flex items-center gap-2 pl-6 text-xs text-muted">
        {task.due_on ? <DueText dueOn={task.due_on} dueAt={task.due_at} done={done} /> : null}
        {subtasks ? (
          <span className="tabular">
            ↳ {task.completed_subtask_count}/{task.subtask_count}
          </span>
        ) : null}
        {assignee ? (
          <Avatar name={assignee.name} src={assignee.avatar_url} size={18} className="ml-auto" />
        ) : null}
      </div>
    </div>
  );
}

function AddColumn({ onAdd }: { onAdd: (name: string) => void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    if (n) onAdd(n);
    setName('');
    setAdding(false);
  };
  if (!adding) {
    return (
      <button
        type="button"
        onClick={() => setAdding(true)}
        className="flex h-9 w-64 shrink-0 items-center gap-1.5 rounded-lg px-3 text-[13px] text-muted hover:bg-surface-2/60 hover:text-ink"
      >
        <Icon icon={Plus} size={15} /> Add column
      </button>
    );
  }
  return (
    <form onSubmit={submit} className="w-64 shrink-0">
      <Input
        aria-label="New column name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => !name.trim() && setAdding(false)}
        onKeyDown={(e) => e.key === 'Escape' && (setAdding(false), setName(''))}
        placeholder="Column name"
        // eslint-disable-next-line jsx-a11y/no-autofocus -- user just asked to add a column
        autoFocus
      />
    </form>
  );
}

const collisions: CollisionDetection = (args) => {
  const within = pointerWithin(args);
  return within.length ? within : closestCenter(args);
};
