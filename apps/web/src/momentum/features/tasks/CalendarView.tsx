import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { CompleteCheck } from '@/components/common/CompleteCheck';
import { ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePeople, type Person } from '@/features/people';
import { useSections } from '@/features/sections';
import { addDays, dayDiff, fromISODate, toISODate } from '@/lib/dates';
import { applyRealtimeEvent, useChannel } from '@/lib/realtime';
import { cn } from '@/lib/cn';
import { useProjectTasks, useTaskMutations, type Task } from './queries';
import { useTaskNav } from './pane/nav';

const INTERACTIVE = 'button, input, textarea, a, [role="checkbox"]';
const MAX_SPAN_DAYS = 62; // ample for any real milestone/multi-day task; guards against runaway loops

const MONTH_LABEL = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' });
const CELL_LABEL = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
const WEEK_DAY_LABEL = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
// Monday-first weekday initials, matching DatePicker's Calendar
const WEEKDAYS = Array.from({ length: 7 }, (_, i) =>
  new Intl.DateTimeFormat(undefined, { weekday: 'narrow' }).format(new Date(2024, 0, 1 + i)),
);

type Part = 'single' | 'start' | 'mid' | 'end';
type ChipData = { kind: 'calendar-task'; task: Task };
type DropData = { kind: 'day'; date: string } | { kind: 'tray' };

const isChip = (data: unknown): data is ChipData =>
  !!data && typeof data === 'object' && (data as { kind?: string }).kind === 'calendar-task';

const mondayOf = (d: Date) => addDays(d, -((d.getDay() + 6) % 7));

/** The days a task occupies on the grid: just its due date, or every day from start to due
 * (inclusive) when it has both and they differ. Capped at MAX_SPAN_DAYS as a sanity guard. */
function spanOf(task: Task): string[] | null {
  if (!task.due_on) return null;
  if (!task.start_on || task.start_on >= task.due_on) return [task.due_on];
  const out: string[] = [];
  let d = fromISODate(task.start_on);
  const end = fromISODate(task.due_on);
  while (toISODate(d) <= toISODate(end) && out.length < MAX_SPAN_DAYS) {
    out.push(toISODate(d));
    d = addDays(d, 1);
  }
  return out;
}

/** Calendar view (S2.2.2): month/week grid of tasks by due date, a "No date" tray for the
 * rest. Pure frontend layer over Phase 1 data — reuses the existing task mutations, no new
 * backend endpoints. Drag a card to a day to reschedule it (or into the tray to clear its due
 * date); ⌘←/→ on a focused card is the keyboard equivalent, with an undo toast. Multi-day tasks
 * (`start_on` before `due_on`) render as a bar spanning their range; only the first day's segment
 * is interactive (draggable/focusable) — the rest are a visual continuation. Resizing a bar's
 * span by dragging its edge is out of scope for this slice (documented in STATUS.md); moving the
 * whole bar is supported.
 */
export function CalendarView({
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
  const open = useProjectTasks(projectId);
  const sections = useSections(projectId);
  const people = usePeople().data;
  const m = useTaskMutations(projectId);
  const nav = useTaskNav();
  const containerRef = useRef<HTMLDivElement>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const [mode, setMode] = useState<'month' | 'week'>('month');
  const [cursor, setCursor] = useState(() => new Date());
  const [focused, setFocused] = useState<string | null>(null);

  const peopleById = useMemo(() => new Map((people ?? []).map((p) => [p.id, p])), [people]);
  const byDay = useMemo(() => {
    const map = new Map<string, { task: Task; part: Part }[]>();
    for (const t of open.data ?? []) {
      const span = spanOf(t);
      if (!span) continue;
      span.forEach((iso, i) => {
        const part: Part =
          span.length === 1 ? 'single' : i === 0 ? 'start' : i === span.length - 1 ? 'end' : 'mid';
        const list = map.get(iso);
        if (list) list.push({ task: t, part });
        else map.set(iso, [{ task: t, part }]);
      });
    }
    for (const list of map.values())
      list.sort((a, b) => ((a.task.due_on ?? '') < (b.task.due_on ?? '') ? -1 : 1));
    return map;
  }, [open.data]);
  const noDate = useMemo(() => (open.data ?? []).filter((t) => !t.due_on), [open.data]);

  const monthStart = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const gridStart = mode === 'month' ? mondayOf(monthStart) : mondayOf(cursor);
  const days = Array.from({ length: mode === 'month' ? 42 : 7 }, (_, i) => addDays(gridStart, i));

  const shift = (n: number) =>
    setCursor((d) => (mode === 'month' ? new Date(d.getFullYear(), d.getMonth() + n, 1) : addDays(d, n * 7)));

  const reschedule = (task: Task, iso: string, message?: string) => {
    if (task.due_on === iso) return;
    let startOn = task.start_on;
    if (task.start_on && task.due_on) {
      const delta = dayDiff(fromISODate(task.due_on), fromISODate(iso));
      startOn = toISODate(addDays(fromISODate(task.start_on), delta));
    }
    m.update.mutate({ id: task.id, patch: { due_on: iso, start_on: startOn }, message });
  };
  const clearDate = (task: Task) => {
    if (!task.due_on) return;
    m.update.mutate({ id: task.id, patch: { due_on: null, start_on: null }, message: 'Moved to No date' });
  };

  const onDragEnd = (e: DragEndEvent) => {
    const chip = e.active.data.current;
    const drop = e.over?.data.current as DropData | undefined;
    if (!isChip(chip) || !drop) return;
    if (drop.kind === 'day')
      reschedule(chip.task, drop.date, `Moved to ${WEEK_DAY_LABEL.format(fromISODate(drop.date))}`);
    else clearDate(chip.task);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const taskId = target.dataset?.taskId;
    if (taskId === undefined) return;
    const task = (open.data ?? []).find((t) => t.id === taskId);
    if (!task) return;
    if (e.key === 'Enter') {
      e.preventDefault();
      nav?.open(task.id);
      return;
    }
    if ((e.metaKey || e.ctrlKey) && (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && task.due_on) {
      if (!canEdit) return;
      e.preventDefault();
      const iso = toISODate(addDays(fromISODate(task.due_on), e.key === 'ArrowRight' ? 1 : -1));
      reschedule(task, iso, `Moved to ${WEEK_DAY_LABEL.format(fromISODate(iso))}`);
    }
  };

  if (open.isPending || sections.isPending) {
    return (
      <div className="grid grid-cols-7 gap-2">
        {Array.from({ length: 14 }, (_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    );
  }
  if (open.isError) return <ErrorState error={open.error} onRetry={() => void open.refetch()} />;
  if (sections.isError) return <ErrorState error={sections.error} onRetry={() => void sections.refetch()} />;

  const firstSectionId = sections.data[0]?.id ?? null;
  const addOn = (iso: string, title: string) => {
    if (!firstSectionId) return;
    // Set the due date only once `create`'s own optimistic entry has been replaced by the
    // server's real one (its onCreated callback, not the temp id it returns): `create` fully
    // overwrites that row when it resolves, so patching the temp id right away would get
    // clobbered by that overwrite and silently lost.
    m.create({ title, sectionId: firstSectionId, afterId: null }, (realId) =>
      m.update.mutate({ id: realId, patch: { due_on: iso } }),
    );
  };

  return (
    // Keyboard handling delegated from focusable chips, like BoardView's outer container.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div ref={containerRef} className="flex h-full min-h-0 gap-4" onKeyDown={onKeyDown}>
      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="mb-3 flex items-center gap-2">
            <IconButton
              icon={ChevronLeft}
              label={mode === 'month' ? 'Previous month' : 'Previous week'}
              size="icon-sm"
              onClick={() => shift(-1)}
            />
            <IconButton
              icon={ChevronRight}
              label={mode === 'month' ? 'Next month' : 'Next week'}
              size="icon-sm"
              onClick={() => shift(1)}
            />
            <Button size="sm" variant="ghost" onClick={() => setCursor(new Date())}>
              Today
            </Button>
            <span className="ml-1 text-sm font-medium">
              {mode === 'month'
                ? MONTH_LABEL.format(cursor)
                : `${WEEK_DAY_LABEL.format(days[0]!)} – ${WEEK_DAY_LABEL.format(days[6]!)}`}
            </span>
            <div className="ml-auto flex rounded-md bg-surface-2 p-0.5 text-sm">
              {(['month', 'week'] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={mode === v}
                  onClick={() => setMode(v)}
                  className={cn(
                    'rounded px-2.5 py-1 capitalize',
                    mode === v ? 'bg-surface shadow-sm' : 'text-muted hover:text-ink',
                  )}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-7 text-center text-xs text-muted-2">
            {WEEKDAYS.map((w, i) => (
              <span key={i} className="pb-1">
                {w}
              </span>
            ))}
          </div>
          <div
            className={cn(
              'grid min-h-0 flex-1 grid-cols-7 gap-1',
              mode === 'month' ? 'grid-rows-6' : 'grid-rows-1',
            )}
          >
            {days.map((d) => {
              const iso = toISODate(d);
              return (
                <Day
                  key={iso}
                  date={d}
                  outside={mode === 'month' && d.getMonth() !== cursor.getMonth()}
                  chips={byDay.get(iso) ?? []}
                  peopleById={peopleById}
                  focused={focused}
                  canEdit={canEdit && !!firstSectionId}
                  color={color}
                  onFocusChip={setFocused}
                  onOpen={(id) => nav?.open(id)}
                  onToggle={(t) => m.setCompleted.mutate({ id: t.id, completed: !t.completed_at })}
                  onAdd={(title) => addOn(iso, title)}
                />
              );
            })}
          </div>
        </div>
        <NoDateTray
          tasks={noDate}
          peopleById={peopleById}
          focused={focused}
          color={color}
          onFocusChip={setFocused}
          onOpen={(id) => nav?.open(id)}
          onToggle={(t) => m.setCompleted.mutate({ id: t.id, completed: !t.completed_at })}
        />
      </DndContext>
    </div>
  );
}

function Day({
  date,
  outside,
  chips,
  peopleById,
  focused,
  canEdit,
  color,
  onFocusChip,
  onOpen,
  onToggle,
  onAdd,
}: {
  date: Date;
  outside: boolean;
  chips: { task: Task; part: Part }[];
  peopleById: Map<string, Person>;
  focused: string | null;
  canEdit: boolean;
  color: string | null;
  onFocusChip: (id: string) => void;
  onOpen: (id: string) => void;
  onToggle: (t: Task) => void;
  onAdd: (title: string) => void;
}) {
  const iso = toISODate(date);
  const drop = useDroppable({ id: `day:${iso}`, data: { kind: 'day', date: iso } satisfies DropData });
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const isToday = iso === toISODate(new Date());

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const t = title.trim();
    if (t) onAdd(t);
    setTitle('');
    setAdding(false);
  };

  return (
    <div
      ref={drop.setNodeRef}
      role="gridcell"
      data-date={iso}
      aria-label={CELL_LABEL.format(date)}
      className={cn(
        'flex min-h-0 min-w-0 flex-col gap-0.5 rounded-md border border-hair-soft p-1',
        outside && 'bg-surface-2/40',
        drop.isOver && 'ring-1 ring-focus ring-inset',
      )}
    >
      <div className="flex items-center justify-between px-0.5">
        <span
          className={cn(
            'tabular text-xs',
            outside && 'text-muted-2',
            isToday && 'flex h-5 w-5 items-center justify-center rounded-full bg-accent text-on-accent',
          )}
        >
          {date.getDate()}
        </span>
        {canEdit ? (
          <IconButton icon={Plus} label="Add task" size="icon-sm" onClick={() => setAdding(true)} />
        ) : null}
      </div>
      <div
        role="list"
        aria-label={`Tasks on ${iso}`}
        className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto"
      >
        {chips.map(({ task, part }) => (
          <Chip
            key={task.id}
            task={task}
            part={part}
            color={color}
            assignee={task.assignee_id ? peopleById.get(task.assignee_id) : undefined}
            focused={focused === task.id}
            onFocus={() => onFocusChip(task.id)}
            onOpen={() => onOpen(task.id)}
            onToggle={() => onToggle(task)}
          />
        ))}
      </div>
      {adding ? (
        <form onSubmit={submit}>
          <Input
            aria-label="New task title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => !title.trim() && setAdding(false)}
            onKeyDown={(e) => e.key === 'Escape' && (setAdding(false), setTitle(''))}
            placeholder="Task name"
            className="h-6 text-[12px]"
            // eslint-disable-next-line jsx-a11y/no-autofocus -- user just asked to add a task here
            autoFocus
          />
        </form>
      ) : null}
    </div>
  );
}

function Chip({
  task,
  part,
  color,
  assignee,
  focused,
  onFocus,
  onOpen,
  onToggle,
}: {
  task: Task;
  part: Part;
  color: string | null;
  assignee: Person | undefined;
  focused: boolean;
  onFocus: () => void;
  onOpen: () => void;
  onToggle: () => void;
}) {
  const done = !!task.completed_at;
  const interactive = part === 'single' || part === 'start';
  const drag = useDraggable({
    id: task.id,
    data: { kind: 'calendar-task', task } satisfies ChipData,
    disabled: !interactive,
  });

  if (!interactive) {
    // A visual continuation of a multi-day bar: not focusable or draggable on its own.
    return (
      <div aria-hidden className={cn('h-5 shrink-0 bg-accent-tint', part === 'end' ? 'rounded-r-sm' : '')} />
    );
  }

  return (
    // Keyboard handling (Enter, ⌘←/→) is delegated from CalendarView's outer container.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/click-events-have-key-events
    <div
      ref={drag.setNodeRef}
      role="listitem"
      aria-label={task.title}
      data-task-id={task.id}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={focused ? 0 : -1}
      onFocus={onFocus}
      onClick={(e) => {
        if (!(e.target as HTMLElement).closest(INTERACTIVE)) onOpen();
      }}
      {...drag.listeners}
      style={color ? { borderLeft: `2px solid var(--${color})` } : undefined}
      className={cn(
        'flex shrink-0 cursor-pointer items-center gap-1 rounded-sm bg-accent-tint px-1 py-0.5 text-[11.5px] outline-none',
        'hover:brightness-95 focus-visible:shadow-[inset_0_0_0_2px_var(--focus)]',
        drag.isDragging && 'opacity-40',
      )}
    >
      <CompleteCheck
        checked={done}
        label={done ? `Mark ${task.title} incomplete` : `Complete ${task.title}`}
        onChange={onToggle}
      />
      <span className={cn('min-w-0 flex-1 truncate', done && 'text-muted line-through')}>{task.title}</span>
      {assignee ? <Avatar name={assignee.name} src={assignee.avatar_url} size={14} /> : null}
    </div>
  );
}

function NoDateTray({
  tasks,
  peopleById,
  focused,
  color,
  onFocusChip,
  onOpen,
  onToggle,
}: {
  tasks: Task[];
  peopleById: Map<string, Person>;
  focused: string | null;
  color: string | null;
  onFocusChip: (id: string) => void;
  onOpen: (id: string) => void;
  onToggle: (t: Task) => void;
}) {
  const drop = useDroppable({ id: 'tray', data: { kind: 'tray' } satisfies DropData });
  return (
    <aside
      ref={drop.setNodeRef}
      aria-label="No date"
      className={cn(
        'flex w-56 shrink-0 flex-col gap-1 overflow-y-auto rounded-md border border-hair-soft p-2',
        drop.isOver && 'ring-1 ring-focus ring-inset',
      )}
    >
      <div className="flex items-center justify-between px-0.5 pb-1">
        <span className="text-xs font-medium text-muted">No date</span>
        <span className="tabular text-xs text-muted-2">{tasks.length}</span>
      </div>
      <div role="list" aria-label="Tasks with no date" className="flex flex-col gap-1">
        {tasks.map((t) => (
          <Chip
            key={t.id}
            task={t}
            part="single"
            color={color}
            assignee={t.assignee_id ? peopleById.get(t.assignee_id) : undefined}
            focused={focused === t.id}
            onFocus={() => onFocusChip(t.id)}
            onOpen={() => onOpen(t.id)}
            onToggle={() => onToggle(t)}
          />
        ))}
      </div>
    </aside>
  );
}
