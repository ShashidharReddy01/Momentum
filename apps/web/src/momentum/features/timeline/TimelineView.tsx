import { useQueryClient } from '@tanstack/react-query';
import { useVirtualizer } from '@tanstack/react-virtual';
import { AlertTriangle, CalendarRange, ChevronDown, ChevronRight, Route } from 'lucide-react';
import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from 'react';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePeople, type Person } from '@/features/people';
import { useSections } from '@/features/sections';
import { useProjectTasks, useTaskMutations, useTaskNav, type Task } from '@/features/tasks';
import { cn } from '@/lib/cn';
import { dayDiff, fromISODate, toISODate } from '@/lib/dates';
import { applyRealtimeEvent, useChannel } from '@/lib/realtime';
import {
  DAY_WIDTH,
  ROW_HEIGHT,
  ZOOMS,
  arrowPath,
  cascadeOf,
  conflictsOf,
  criticalPath,
  datePatch,
  draggedSpan,
  edgeKey,
  rangeOf,
  rowsOf,
  spanOf,
  ticksOf,
  xOf,
  type DragMode,
  type Row,
  type Zoom,
} from './layout';
import { toastError } from '@/lib/toast';
import { CascadeDialog } from './CascadeDialog';
import {
  useProjectDependencies,
  useReschedule,
  type DatesPatch,
  type DependencyEdge,
  type ReschedulePlan,
} from './queries';

const LEFT = 280; // task column
const HEADER = 48; // two tick bands
const BAR_H = 20;
const DIAMOND = 14;
const ZOOM_LABEL: Record<Zoom, string> = { week: 'Week', month: 'Month', quarter: 'Quarter' };
const DATE = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });

const fmt = (iso: string) => DATE.format(fromISODate(iso));
const rangeText = (s: { start: string; end: string }) => {
  const days = dayDiff(fromISODate(s.start), fromISODate(s.end)) + 1;
  return s.start === s.end ? fmt(s.start) : `${fmt(s.start)} – ${fmt(s.end)} · ${days} days`;
};

type Span = { start: string; end: string };
type Hover = { task: Task; span: Span; x: number; y: number };

/** A drag in progress: a bar being moved or resized, or an unscheduled task being dropped on a
 * day. Kept in a ref for the window listeners and mirrored in state for rendering. */
type Drag =
  | {
      kind: 'bar';
      task: Task;
      span: Span;
      mode: DragMode;
      originX: number;
      startClientX: number;
      days: number;
    }
  | { kind: 'tray'; task: Task; clientX: number; clientY: number; day: string | null };

const MIN_DRAG_PX = 4; // below this a press is a click (opens the task)

/** A move waiting on the server's cascade preview or the person's answer to it (S6.1.2). */
type Pending = { task: Task; patch: DatesPatch; message: string; plan: ReschedulePlan | null };

/**
 * Timeline view (S6.1.1a): top-level tasks as bars on a time axis, grouped by section.
 *
 * What it shows at a glance, beyond a plain Gantt: the **critical path** (the chain of dependent
 * work that sets the end date, outlined in the accent), **conflicts** (a task drawn to start
 * before its blocker is due: the arrow turns crit and the toolbar counts them, one click jumps to
 * the first), overdue bars, subtask progress inside each bar, and every section's overall span.
 *
 * Rows are virtualized with a fixed height (like the list), so 500 tasks mount only what's on
 * screen; arrows are drawn only for edges that touch the visible rows. The task column is sticky
 * on the left and the time header sticky on top of one scroll container, so both axes scroll
 * together.
 *
 * Editing (S6.1.1b, editors only): drag a bar to move it, drag its edges to change the start or
 * due date, drag an unscheduled task onto a day to schedule it, `←/→` nudges the focused task a day
 * (`Shift`: a week), `J/K` move between tasks, `Esc` cancels a drag. While dragging, the task's
 * new dates are fed through the same layout, so its arrows, conflicts and the critical path update
 * live. Every change goes through `useTaskMutations().update` (optimistic, undo toast, realtime).
 */
export function TimelineView({
  projectId,
  canEdit,
  color,
  projectDue = null,
}: {
  projectId: string;
  canEdit: boolean;
  color: string | null;
  /** The project's own due date (S6.2.1), drawn as a dashed "Due" line. */
  projectDue?: string | null;
}) {
  const qc = useQueryClient();
  useChannel(`project:${projectId}`, (event) => applyRealtimeEvent(qc, event, { projectId }));
  const [zoom, setZoom] = useState<Zoom>('month');
  const [showCompleted, setShowCompleted] = useState(false);
  const [showCritical, setShowCritical] = useState(true);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  const [hover, setHover] = useState<Hover | null>(null);
  const open = useProjectTasks(projectId);
  const done = useProjectTasks(projectId, true, showCompleted);
  const sections = useSections(projectId);
  const deps = useProjectDependencies(projectId);
  const people = usePeople('', 'all').data;
  const nav = useTaskNav();
  const m = useTaskMutations(projectId);
  const reschedule = useReschedule(projectId);
  const [pending, setPending] = useState<Pending | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingCenter = useRef<number | null>(null);
  const [drag, setDragState] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const suppressClick = useRef(false);
  const setDrag = useCallback((d: Drag | null) => {
    dragRef.current = d;
    setDragState(d);
  }, []);

  const today = useMemo(() => new Date(), []);
  const saved = useMemo(
    () => [...(open.data ?? []), ...(showCompleted ? (done.data ?? []) : [])],
    [open.data, done.data, showCompleted],
  );
  // what's drawn: the saved tasks, with a dragged bar's dates replaced by where it is now
  const tasks = useMemo(() => {
    if (pending) return saved.map((t) => (t.id === pending.task.id ? { ...t, ...pending.patch } : t));
    if (drag?.kind !== 'bar' || drag.days === 0) return saved;
    const patch = datePatch(drag.task, draggedSpan(drag.span, drag.mode, drag.days), drag.mode);
    return patch ? saved.map((t) => (t.id === drag.task.id ? { ...t, ...patch } : t)) : saved;
  }, [saved, drag, pending]);
  const edges: DependencyEdge[] = useMemo(() => deps.data ?? [], [deps.data]);
  // where the work that waits on a moving task would land (dashed "ghost" bars, S6.1.2)
  const ghosts = useMemo(() => {
    if (pending?.plan)
      return new Map(
        pending.plan.shifted.map((c) => [
          c.id,
          spanOf({ ...pending.task, type: 'task', start_on: c.to_start, due_on: c.to_due })!,
        ]),
      );
    if (drag?.kind !== 'bar' || drag.days === 0) return new Map<string, Span>();
    return cascadeOf(saved, edges, drag.task.id, draggedSpan(drag.span, drag.mode, drag.days));
  }, [drag, pending, saved, edges]);
  const { rows, unscheduled } = useMemo(
    () => rowsOf(sections.data ?? [], tasks, collapsed),
    [sections.data, tasks, collapsed],
  );
  const range = useMemo(
    () =>
      rangeOf(
        saved.map(spanOf).filter((s): s is Span => !!s),
        today,
      ),
    [saved, today],
  );
  const dw = DAY_WIDTH[zoom];
  const width = range.days * dw;
  const ticks = useMemo(() => ticksOf(range.start, range.days, zoom, today), [range, zoom, today]);
  const critical = useMemo(() => criticalPath(tasks, edges), [tasks, edges]);
  const criticalSet = useMemo(() => new Set(showCritical ? critical : []), [critical, showCritical]);
  // from the earliest start to the latest end on the chain (a chain drawn out of order, with
  // conflicts, still spans all of its tasks)
  const criticalDays = useMemo(() => {
    const spans = critical.map((id) => spanOf(tasks.find((t) => t.id === id)!)!);
    if (!spans.length) return 0;
    const first = spans.reduce((a, s) => (s.start < a ? s.start : a), spans[0]!.start);
    const last = spans.reduce((a, s) => (s.end > a ? s.end : a), spans[0]!.end);
    return dayDiff(fromISODate(first), fromISODate(last)) + 1;
  }, [critical, tasks]);
  const conflicts = useMemo(() => conflictsOf(tasks, edges), [tasks, edges]);
  const rowIndex = useMemo(() => {
    const m = new Map<string, number>();
    rows.forEach((r, i) => r.kind === 'task' && m.set(r.task.id, i));
    return m;
  }, [rows]);
  const sectionSpans = useMemo(() => {
    const m = new Map<string, { start: string; end: string }>();
    for (const t of tasks) {
      const s = spanOf(t);
      if (!s || !t.section_id) continue;
      const cur = m.get(t.section_id);
      m.set(
        t.section_id,
        cur
          ? { start: s.start < cur.start ? s.start : cur.start, end: s.end > cur.end ? s.end : cur.end }
          : s,
      );
    }
    return m;
  }, [tasks]);
  const peopleById = useMemo(() => new Map((people ?? []).map((p) => [p.id, p])), [people]);
  const conflictTasks = useMemo(() => {
    const ids = new Set<string>();
    for (const e of edges) if (conflicts.has(edgeKey(e))) ids.add(e.task_id);
    return ids;
  }, [edges, conflicts]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    paddingStart: HEADER,
  });
  const items = virtualizer.getVirtualItems();
  const firstIndex = items[0]?.index ?? 0;
  const lastIndex = items[items.length - 1]?.index ?? -1;

  const todayX = xOf(range.start, toISODate(today), dw);
  const ready = !open.isPending && !sections.isPending;

  // First paint: put today a little right of the task column. After a zoom change: keep
  // whatever date was in the middle of the view in the middle.
  const scrolledOnce = useRef(false);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !ready) return;
    const visible = Math.max(0, el.clientWidth - LEFT);
    if (pendingCenter.current !== null) {
      el.scrollLeft = Math.max(0, pendingCenter.current * dw - visible / 2);
      pendingCenter.current = null;
    } else if (!scrolledOnce.current) {
      el.scrollLeft = Math.max(0, todayX - Math.min(160, visible / 4));
      scrolledOnce.current = true;
    }
  }, [dw, ready, todayX]);

  const changeZoom = useCallback(
    (next: Zoom) => {
      const el = scrollRef.current;
      if (el && next !== zoom) {
        const visible = Math.max(0, el.clientWidth - LEFT);
        pendingCenter.current = (el.scrollLeft + visible / 2) / dw;
      }
      setZoom(next);
    },
    [dw, zoom],
  );

  const scrollToDate = (x: number) => {
    const el = scrollRef.current;
    if (!el) return;
    const visible = Math.max(0, el.clientWidth - LEFT);
    el.scrollTo({ left: Math.max(0, x - visible / 3), behavior: 'smooth' });
  };

  const jumpToConflict = () => {
    const first = rows.findIndex((r) => r.kind === 'task' && conflictTasks.has(r.task.id));
    if (first < 0) return;
    const r = rows[first] as Extract<Row<Task>, { kind: 'task' }>;
    virtualizer.scrollToIndex(first, { align: 'center' });
    scrollToDate(xOf(range.start, r.span.start, dw));
  };

  const toggleSection = useCallback((id: string) => {
    setCollapsed((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const openTask = useCallback(
    (id: string) => {
      if (suppressClick.current) {
        suppressClick.current = false; // the click that ends a drag
        return;
      }
      nav?.open(id);
    },
    [nav],
  );

  const saveDates = useCallback(
    (task: Task, span: Span, mode: DragMode, verb: string) => {
      const patch = datePatch(task, span, mode);
      if (!patch) return;
      const when =
        task.type === 'milestone' || span.start === span.end
          ? fmt(span.end)
          : `${fmt(span.start)} – ${fmt(span.end)}`;
      const message = `${verb} ${task.key} to ${when}`;
      const old = spanOf(task);
      // only a later end can push anything; earlier moves and new dates save straight away
      if (!old || span.end <= old.end) {
        m.update.mutate({ id: task.id, patch, message });
        return;
      }
      setPending({ task, patch, message, plan: null });
      reschedule
        .preview(task.id, patch)
        .then((plan) => {
          if (plan.shifted.length || plan.skipped.length || plan.hidden_skipped) {
            setPending({ task, patch, message, plan });
          } else {
            setPending(null);
            m.update.mutate({ id: task.id, patch, message });
          }
        })
        .catch((e: unknown) => {
          setPending(null);
          toastError(e, "Couldn't check the tasks that wait on this one");
        });
    },
    [m.update, reschedule],
  );

  const moveAll = () => {
    if (!pending?.plan) return;
    const { task, patch, plan } = pending;
    const n = plan.shifted.length;
    reschedule.apply.mutate(
      {
        taskId: task.id,
        patch,
        message: n ? `Moved ${task.key} and ${n} ${n === 1 ? 'task' : 'tasks'} after it` : pending.message,
      },
      { onSettled: () => setPending(null) },
    );
  };
  const moveOnly = () => {
    if (!pending) return;
    m.update.mutate({ id: pending.task.id, patch: pending.patch, message: pending.message });
    setPending(null);
  };

  const dayAt = useCallback(
    (clientX: number): string | null => {
      const el = scrollRef.current;
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      const x = clientX - rect.left - LEFT + el.scrollLeft;
      if (clientX < rect.left + LEFT || clientX > rect.right || x < 0) return null;
      const day = new Date(range.start);
      day.setDate(day.getDate() + Math.floor(x / dw));
      return toISODate(day);
    },
    [range.start, dw],
  );

  const startBarDrag = useCallback(
    (task: Task, span: Span, mode: DragMode, clientX: number) => {
      if (!canEdit) return;
      const left = scrollRef.current?.scrollLeft ?? 0;
      setHover(null);
      setDrag({ kind: 'bar', task, span, mode, originX: clientX + left, startClientX: clientX, days: 0 });
    },
    [canEdit, setDrag],
  );

  const startTrayDrag = useCallback(
    (task: Task, clientX: number, clientY: number) => {
      if (!canEdit) return;
      setDrag({ kind: 'tray', task, clientX, clientY, day: null });
    },
    [canEdit, setDrag],
  );

  // window listeners for the drag in progress
  const dragging = drag !== null;
  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;
      if (d.kind === 'bar') {
        const left = scrollRef.current?.scrollLeft ?? 0;
        const days = Math.round((e.clientX + left - d.originX) / dw);
        if (days !== d.days) setDrag({ ...d, days });
      } else {
        setDrag({ ...d, clientX: e.clientX, clientY: e.clientY, day: dayAt(e.clientX) });
      }
    };
    const onUp = (e: PointerEvent) => {
      const d = dragRef.current;
      setDrag(null);
      if (!d) return;
      if (d.kind === 'bar') {
        if (Math.abs(e.clientX - d.startClientX) < MIN_DRAG_PX) return; // a click
        suppressClick.current = true;
        setTimeout(() => (suppressClick.current = false), 0);
        if (d.days !== 0)
          saveDates(
            d.task,
            draggedSpan(d.span, d.mode, d.days),
            d.mode,
            d.mode === 'move' ? 'Moved' : 'Changed',
          );
      } else {
        const day = dayAt(e.clientX);
        if (!day) return;
        suppressClick.current = true;
        setTimeout(() => (suppressClick.current = false), 0);
        m.update.mutate({
          id: d.task.id,
          patch: { due_on: day },
          message: `Scheduled ${d.task.key} for ${fmt(day)}`,
        });
      }
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') setDrag(null);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('keydown', onKey);
    };
  }, [dragging, dw, dayAt, saveDates, setDrag, m.update]);

  const focusBar = (id: string) => {
    let tries = 0;
    const attempt = () => {
      const el = scrollRef.current?.querySelector<HTMLElement>(`[data-bar="${id}"]`);
      if (el) el.focus();
      else if (tries++ < 5) requestAnimationFrame(attempt);
    };
    attempt();
  };

  const onBarKey = useCallback(
    (task: Task, span: Span, e: KeyboardEvent<HTMLButtonElement>) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && canEdit) {
        e.preventDefault();
        const days = (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 7 : 1);
        saveDates(task, draggedSpan(span, 'move', days), 'move', 'Moved');
        return;
      }
      if (e.key === 'j' || e.key === 'k') {
        e.preventDefault();
        const i = rowIndex.get(task.id);
        if (i === undefined) return;
        const step = e.key === 'j' ? 1 : -1;
        for (let n = i + step; n >= 0 && n < rows.length; n += step) {
          const r = rows[n]!;
          if (r.kind === 'task') {
            virtualizer.scrollToIndex(n, { align: 'auto' });
            focusBar(r.task.id);
            return;
          }
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canEdit, saveDates, rowIndex, rows],
  );

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!(e.metaKey || e.ctrlKey)) return;
    const i = ZOOMS.indexOf(zoom);
    if ((e.key === '=' || e.key === '+') && i > 0) {
      e.preventDefault();
      changeZoom(ZOOMS[i - 1]!);
    } else if (e.key === '-' && i < ZOOMS.length - 1) {
      e.preventDefault();
      changeZoom(ZOOMS[i + 1]!);
    }
  };

  if (!ready) {
    return (
      <div className="flex flex-col gap-2" aria-busy="true">
        <Skeleton className="h-8 w-72" />
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} style={{ marginLeft: `${(i * 37) % 200}px`, width: `${30 + ((i * 13) % 40)}%` }}>
            <Skeleton className="h-7" />
          </div>
        ))}
      </div>
    );
  }
  if (open.isError) return <ErrorState error={open.error} onRetry={() => void open.refetch()} />;
  if (sections.isError) return <ErrorState error={sections.error} onRetry={() => void sections.refetch()} />;
  if (tasks.length === 0) {
    return (
      <EmptyState icon={CalendarRange} title="No tasks yet">
        Add tasks in the List view, give them start and due dates, and they'll appear here as a plan.
      </EmptyState>
    );
  }

  const scheduledCount = rowIndex.size;
  const total = virtualizer.getTotalSize();
  const bodyHeight = total - HEADER;
  const weekendStripes: CSSProperties | undefined =
    zoom === 'quarter'
      ? undefined
      : {
          backgroundImage: `repeating-linear-gradient(to right, transparent 0, transparent ${5 * dw}px, var(--surface-2) ${5 * dw}px, var(--surface-2) ${7 * dw}px)`,
        };

  // arrows touching the visible rows (an edge crossing the viewport counts too)
  const arrows: { key: string; d: string; kind: 'normal' | 'critical' | 'conflict' }[] = [];
  const byId = new Map(tasks.map((t) => [t.id, t]));
  for (const e of edges) {
    const a = rowIndex.get(e.depends_on_id);
    const b = rowIndex.get(e.task_id);
    if (a === undefined || b === undefined) continue;
    if (Math.max(a, b) < firstIndex || Math.min(a, b) > lastIndex) continue;
    const from = spanOf(byId.get(e.depends_on_id)!)!;
    const to = spanOf(byId.get(e.task_id)!)!;
    const fromMilestone = byId.get(e.depends_on_id)!.type === 'milestone';
    const toMilestone = byId.get(e.task_id)!.type === 'milestone';
    const x1 = fromMilestone
      ? xOf(range.start, from.end, dw) + dw / 2 + DIAMOND / 2
      : xOf(range.start, from.end, dw) + dw;
    const x2 = toMilestone
      ? xOf(range.start, to.start, dw) + dw / 2 - DIAMOND / 2
      : xOf(range.start, to.start, dw);
    const k = edgeKey(e);
    const isCritical =
      criticalSet.has(e.task_id) &&
      criticalSet.has(e.depends_on_id) &&
      critical.indexOf(e.task_id) === critical.indexOf(e.depends_on_id) + 1;
    arrows.push({
      key: k,
      d: arrowPath(x1, a * ROW_HEIGHT + ROW_HEIGHT / 2, x2, b * ROW_HEIGHT + ROW_HEIGHT / 2),
      kind: conflicts.has(k) ? 'conflict' : isCritical ? 'critical' : 'normal',
    });
  }

  return (
    <div className="flex h-full min-h-0 gap-4">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mb-3 flex flex-wrap items-center gap-2" role="toolbar" aria-label="Timeline">
          <Button size="sm" variant="ghost" onClick={() => scrollToDate(todayX)}>
            Today
          </Button>
          <div className="flex rounded-md bg-surface-2 p-0.5 text-sm" role="group" aria-label="Zoom">
            {ZOOMS.map((z) => (
              <button
                key={z}
                type="button"
                aria-pressed={zoom === z}
                onClick={() => changeZoom(z)}
                className={cn(
                  'rounded px-2.5 py-1',
                  zoom === z ? 'bg-surface shadow-sm' : 'text-muted hover:text-ink',
                )}
              >
                {ZOOM_LABEL[z]}
              </button>
            ))}
          </div>
          {critical.length ? (
            <button
              type="button"
              aria-pressed={showCritical}
              onClick={() => setShowCritical((v) => !v)}
              title="The chain of dependent work that sets the end date"
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
                showCritical
                  ? 'border-accent bg-accent-tint text-ink'
                  : 'border-hairline text-muted hover:text-ink',
              )}
            >
              <Icon icon={Route} size={14} />
              Critical path · {critical.length} tasks, {criticalDays} days
            </button>
          ) : null}
          {conflictTasks.size ? (
            <button
              type="button"
              onClick={jumpToConflict}
              title="Tasks drawn to start before their blocker is due. Click to jump to the first."
              className="inline-flex items-center gap-1.5 rounded-full bg-crit-tint px-2.5 py-1 text-xs text-crit"
            >
              <Icon icon={AlertTriangle} size={14} />
              {conflictTasks.size} {conflictTasks.size === 1 ? 'conflict' : 'conflicts'}
            </button>
          ) : null}
          <label className="ml-auto flex items-center gap-1.5 text-sm text-muted">
            <input
              type="checkbox"
              checked={showCompleted}
              onChange={(e) => setShowCompleted(e.target.checked)}
            />
            Show completed
          </label>
          <span className="text-xs text-muted-2">
            {scheduledCount} scheduled · {unscheduled.length} unscheduled
          </span>
        </div>

        {/* A scrollable region must be focusable so keyboard users can scroll it (and use ⌘+/⌘-). */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
        <div
          ref={scrollRef}
          role="region"
          aria-label="Timeline chart"
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
          onKeyDown={onKeyDown}
          className="relative min-h-0 flex-1 overflow-auto rounded-lg border border-hairline bg-surface focus-visible:outline-2 focus-visible:outline-focus"
        >
          <div
            className="relative"
            style={{ width: LEFT + width, height: Math.max(total, HEADER + ROW_HEIGHT) }}
          >
            {/* sticky time header */}
            <div
              className="sticky top-0 z-30 flex border-b border-hairline bg-surface"
              style={{ height: HEADER }}
            >
              <div
                className="sticky left-0 z-10 flex shrink-0 items-end border-r border-hairline bg-surface px-3 pb-1.5 text-xs text-muted-2"
                style={{ width: LEFT }}
              >
                Task
              </div>
              <div className="relative shrink-0" style={{ width }} aria-hidden>
                {ticks.major.map((m) => (
                  <div
                    key={m.x}
                    className="absolute top-0 truncate border-l border-hair-soft px-2 pt-1 text-xs font-medium text-ink-2"
                    style={{ left: m.x, width: m.width, height: HEADER / 2 }}
                  >
                    {m.label}
                  </div>
                ))}
                {/* outside week zoom the Today chip marks the day, so labels it would cover step aside */}
                {ticks.minor
                  .filter((t) => zoom === 'week' || Math.abs(t.x - (todayX + dw / 2)) > 30)
                  .map((t) => (
                    <div
                      key={t.x}
                      className={cn(
                        'absolute bottom-0 text-[11px] tabular-nums',
                        zoom === 'week' ? 'text-center' : 'border-l border-hair-soft pl-1',
                        t.weekend ? 'text-muted-2' : 'text-muted',
                        t.today && 'font-semibold text-info',
                      )}
                      style={{
                        left: t.x,
                        width: zoom === 'week' ? dw : undefined,
                        height: HEADER / 2,
                        lineHeight: `${HEADER / 2}px`,
                      }}
                    >
                      {t.label}
                    </div>
                  ))}
                <div
                  hidden={zoom === 'week'}
                  className="absolute bottom-1 rounded-sm bg-info px-1 text-[10px] font-medium leading-4 text-surface"
                  style={{ left: todayX + dw / 2, transform: 'translateX(-50%)' }}
                >
                  Today
                </div>
                {projectDue ? (
                  <div
                    className="absolute top-1 rounded-sm border border-ink-2 bg-surface px-1 text-[10px] leading-4 font-medium text-ink-2"
                    style={{ left: xOf(range.start, projectDue, dw) + dw, transform: 'translateX(-50%)' }}
                    title="The project's due date"
                  >
                    Due
                  </div>
                ) : null}
              </div>
            </div>

            {/* grid: weekends, month lines, today */}
            <div
              className="pointer-events-none absolute"
              style={{ left: LEFT, top: HEADER, width, height: bodyHeight, ...weekendStripes }}
              aria-hidden
            >
              {ticks.major.map((m) => (
                <div
                  key={m.x}
                  className="absolute top-0 h-full border-l border-hair-soft"
                  style={{ left: m.x }}
                />
              ))}
              <div className="absolute top-0 h-full w-0.5 bg-info" style={{ left: todayX + dw / 2 - 1 }} />
              {projectDue ? (
                <div
                  data-project-due
                  className="absolute top-0 h-full border-l-2 border-dashed border-ink-2"
                  style={{ left: xOf(range.start, projectDue, dw) + dw }}
                />
              ) : null}
            </div>

            {/* dependency arrows */}
            <svg
              className="pointer-events-none absolute z-10 overflow-visible"
              style={{ left: LEFT, top: HEADER }}
              width={width}
              height={bodyHeight}
              aria-hidden
            >
              <defs>
                {(['normal', 'critical', 'conflict'] as const).map((k) => (
                  <marker
                    key={k}
                    id={`tl-arrow-${k}`}
                    viewBox="0 0 8 8"
                    refX="7"
                    refY="4"
                    markerWidth="6"
                    markerHeight="6"
                    orient="auto"
                  >
                    <path d="M0,0 L8,4 L0,8 z" fill={ARROW_COLOR[k]} />
                  </marker>
                ))}
              </defs>
              {arrows.map((a) => (
                <path
                  key={a.key}
                  d={a.d}
                  fill="none"
                  stroke={ARROW_COLOR[a.kind]}
                  strokeWidth={a.kind === 'normal' ? 1.25 : 2}
                  strokeDasharray={a.kind === 'conflict' ? '4 3' : undefined}
                  markerEnd={`url(#tl-arrow-${a.kind})`}
                  data-edge={a.key}
                  data-kind={a.kind}
                />
              ))}
            </svg>

            {items.map((item) => {
              const row = rows[item.index]!;
              return row.kind === 'section' ? (
                <SectionRow
                  key={`s-${row.id}`}
                  row={row}
                  top={item.start}
                  span={sectionSpans.get(row.id) ?? null}
                  rangeStart={range.start}
                  dw={dw}
                  width={width}
                  onToggle={toggleSection}
                />
              ) : (
                <TaskRow
                  key={row.task.id}
                  task={row.task}
                  span={row.span}
                  top={item.start}
                  rangeStart={range.start}
                  dw={dw}
                  width={width}
                  color={color}
                  critical={criticalSet.has(row.task.id)}
                  conflict={conflictTasks.has(row.task.id)}
                  person={row.task.assignee_id ? peopleById.get(row.task.assignee_id) : undefined}
                  canEdit={canEdit && !pending}
                  ghost={ghosts.get(row.task.id)}
                  dragging={drag?.kind === 'bar' && drag.task.id === row.task.id}
                  onOpen={openTask}
                  onHover={dragging ? noop : setHover}
                  onDragStart={startBarDrag}
                  onKey={onBarKey}
                />
              );
            })}

            {/* the dates a dragged bar would get, beside it */}
            {drag?.kind === 'bar' && drag.days !== 0
              ? (() => {
                  const i = rowIndex.get(drag.task.id);
                  if (i === undefined) return null;
                  const span = draggedSpan(drag.span, drag.mode, drag.days);
                  return (
                    <div
                      role="status"
                      className="pointer-events-none absolute z-40 rounded-md bg-ink px-2 py-0.5 text-xs whitespace-nowrap text-surface tabular-nums shadow-pop"
                      style={{
                        left: LEFT + xOf(range.start, span.start, dw),
                        top: HEADER + i * ROW_HEIGHT - 22,
                      }}
                    >
                      {rangeText(span)} ({drag.days > 0 ? '+' : ''}
                      {drag.days} {Math.abs(drag.days) === 1 ? 'day' : 'days'})
                      {ghosts.size
                        ? ` · ${ghosts.size} ${ghosts.size === 1 ? 'task follows' : 'tasks follow'}`
                        : ''}
                    </div>
                  );
                })()
              : null}

            {/* the day an unscheduled task would land on */}
            {drag?.kind === 'tray' && drag.day ? (
              <div
                className="pointer-events-none absolute z-10 bg-accent-tint"
                style={{
                  left: LEFT + xOf(range.start, drag.day, dw),
                  top: HEADER,
                  width: dw,
                  height: bodyHeight,
                }}
                aria-hidden
              />
            ) : null}

            {scheduledCount === 0 ? (
              <div
                className="absolute inset-x-0 z-20 flex justify-center"
                style={{ top: HEADER + rows.length * ROW_HEIGHT + 24, left: LEFT }}
              >
                <p className="max-w-sm rounded-lg border border-hairline bg-surface px-4 py-3 text-center text-sm text-muted shadow-sm">
                  <span className="block font-medium text-ink">Nothing scheduled yet</span>
                  Drag tasks from Unscheduled onto a day, or give them a start or due date.
                </p>
              </div>
            ) : null}

            {hover && !drag ? (
              <HoverCard
                hover={hover}
                critical={criticalSet.has(hover.task.id)}
                conflict={conflictTasks.has(hover.task.id)}
                person={hover.task.assignee_id ? peopleById.get(hover.task.assignee_id) : undefined}
              />
            ) : null}
          </div>
        </div>
      </div>
      <CascadeDialog
        plan={pending?.plan ?? null}
        onAll={moveAll}
        onOnly={moveOnly}
        onCancel={() => setPending(null)}
      />
      <UnscheduledTray tasks={unscheduled} canEdit={canEdit} onOpen={openTask} onDragStart={startTrayDrag} />
      {drag?.kind === 'tray' ? (
        <div
          role="status"
          className="pointer-events-none fixed z-50 max-w-60 truncate rounded-md border border-hairline bg-surface px-2 py-1 text-sm shadow-pop"
          style={{ left: drag.clientX + 12, top: drag.clientY + 12 }}
        >
          {drag.task.title}
          <span className="block text-xs text-muted">
            {drag.day ? `Schedule for ${fmt(drag.day)}` : 'Drop on a day to schedule'}
          </span>
        </div>
      ) : null}
    </div>
  );
}

const noop = () => undefined;

const ARROW_COLOR = {
  normal: 'var(--muted-2)',
  critical: 'var(--accent)',
  conflict: 'var(--crit)',
} as const;

const SectionRow = memo(function SectionRow({
  row,
  top,
  span,
  rangeStart,
  dw,
  width,
  onToggle,
}: {
  row: Extract<Row<Task>, { kind: 'section' }>;
  top: number;
  span: { start: string; end: string } | null;
  rangeStart: Date;
  dw: number;
  width: number;
  onToggle: (id: string) => void;
}) {
  const x = span ? xOf(rangeStart, span.start, dw) : 0;
  const w = span ? xOf(rangeStart, span.end, dw) + dw - x : 0;
  return (
    <div
      className="absolute left-0 flex border-b border-hair-soft"
      style={{ top, height: ROW_HEIGHT, width: LEFT + width }}
    >
      <div
        className="sticky left-0 z-20 flex shrink-0 items-center gap-1 border-r border-hairline bg-surface-2 px-2"
        style={{ width: LEFT }}
      >
        <button
          type="button"
          aria-expanded={!row.collapsed}
          onClick={() => onToggle(row.id)}
          className="flex min-w-0 items-center gap-1 rounded px-1 py-0.5 text-sm font-semibold hover:bg-surface"
        >
          <Icon icon={row.collapsed ? ChevronRight : ChevronDown} size={14} className="text-muted" />
          <span className="truncate">{row.name}</span>
        </button>
        <span className="ml-auto text-xs text-muted-2 tabular-nums">{row.count}</span>
      </div>
      <div className="relative shrink-0" style={{ width }}>
        {span ? (
          <div
            className="absolute rounded-full bg-hairline"
            style={{ left: x, width: w, top: ROW_HEIGHT / 2 - 2, height: 4 }}
            title={`${row.name}: ${rangeText(span)}`}
          />
        ) : null}
      </div>
    </div>
  );
});

const TaskRow = memo(function TaskRow({
  task,
  span,
  top,
  rangeStart,
  dw,
  width,
  color,
  critical,
  conflict,
  person,
  canEdit,
  ghost,
  dragging,
  onOpen,
  onHover,
  onDragStart,
  onKey,
}: {
  task: Task;
  span: { start: string; end: string };
  top: number;
  rangeStart: Date;
  dw: number;
  width: number;
  color: string | null;
  critical: boolean;
  conflict: boolean;
  person: Person | undefined;
  canEdit: boolean;
  ghost: Span | undefined;
  dragging: boolean;
  onOpen: (id: string) => void;
  onHover: (h: Hover | null) => void;
  onDragStart: (task: Task, span: Span, mode: DragMode, clientX: number) => void;
  onKey: (task: Task, span: Span, e: KeyboardEvent<HTMLButtonElement>) => void;
}) {
  const done = !!task.completed_at;
  const overdue = !done && span.end < toISODate(new Date());
  const milestone = task.type === 'milestone';
  const x = xOf(rangeStart, span.start, dw);
  const w = Math.max(xOf(rangeStart, span.end, dw) + dw - x, 6);
  const fill = `var(--${color ?? 'accent'})`;
  const progress = task.subtask_count ? task.completed_subtask_count / task.subtask_count : 0;
  const label = `${task.key} ${task.title}, ${rangeText(span)}${done ? ', done' : overdue ? ', overdue' : ''}${
    critical ? ', on the critical path' : ''
  }${conflict ? ', starts before its blocker is due' : ''}`;
  const show = () => onHover({ task, span, x: LEFT + x, y: top });
  const labelLeft = milestone ? x + dw / 2 + DIAMOND : x + w + 8;
  return (
    <div
      className="absolute left-0 flex border-b border-hair-soft"
      style={{ top, height: ROW_HEIGHT, width: LEFT + width }}
      data-task-row={task.id}
    >
      <div
        className="sticky left-0 z-20 flex shrink-0 items-center gap-2 border-r border-hairline bg-surface px-3"
        style={{ width: LEFT }}
      >
        <button
          type="button"
          onClick={() => onOpen(task.id)}
          className={cn(
            'flex min-w-0 flex-1 items-baseline gap-2 text-left text-sm hover:underline',
            done && 'text-muted line-through',
          )}
        >
          <span className="shrink-0 font-mono text-[11px] text-muted-2">{task.key}</span>
          <span className="truncate">{task.title}</span>
        </button>
        {person ? (
          <Avatar name={person.name} src={person.avatar_url} size={20} isAgent={person.is_agent} />
        ) : null}
      </div>
      <div className="relative shrink-0" style={{ width }}>
        <button
          type="button"
          aria-label={label}
          data-bar={task.id}
          onClick={() => onOpen(task.id)}
          onMouseEnter={show}
          onMouseLeave={() => onHover(null)}
          onFocus={show}
          onBlur={() => onHover(null)}
          onKeyDown={(e) => onKey(task, span, e)}
          onPointerDown={(e) => {
            if (!canEdit || e.button !== 0) return;
            e.preventDefault(); // no text selection while dragging
            e.currentTarget.focus();
            const handle = (e.target as HTMLElement).dataset.handle as DragMode | undefined;
            onDragStart(task, span, handle ?? 'move', e.clientX);
          }}
          className={cn(
            'group absolute block touch-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
            canEdit && (dragging ? 'cursor-grabbing shadow-pop' : 'cursor-grab'),
            milestone ? 'rotate-45 rounded-[3px]' : 'overflow-hidden rounded-md',
            done && 'opacity-45',
            critical && 'ring-2 ring-accent ring-offset-1 ring-offset-surface',
            conflict && !critical && 'ring-2 ring-crit ring-offset-1 ring-offset-surface',
          )}
          style={
            milestone
              ? {
                  left: x + dw / 2 - DIAMOND / 2,
                  top: ROW_HEIGHT / 2 - DIAMOND / 2,
                  width: DIAMOND,
                  height: DIAMOND,
                  background: done ? 'var(--muted-2)' : 'var(--ink)',
                }
              : { left: x, top: (ROW_HEIGHT - BAR_H) / 2, width: w, height: BAR_H, background: fill }
          }
        >
          {!milestone && progress > 0 ? (
            <span className="absolute inset-y-0 left-0 bg-ink/25" style={{ width: `${progress * 100}%` }} />
          ) : null}
          {canEdit && !milestone ? (
            <>
              <span
                data-handle="start"
                className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize rounded-l-md group-hover:bg-ink/30"
              />
              <span
                data-handle="end"
                className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize rounded-r-md group-hover:bg-ink/30"
              />
            </>
          ) : null}
        </button>
        {ghost ? (
          <span
            data-ghost={task.id}
            aria-hidden
            className="pointer-events-none absolute rounded-md border-2 border-dashed"
            style={{
              left: xOf(rangeStart, ghost.start, dw),
              width: Math.max(xOf(rangeStart, ghost.end, dw) + dw - xOf(rangeStart, ghost.start, dw), 6),
              top: (ROW_HEIGHT - BAR_H) / 2,
              height: BAR_H,
              borderColor: fill,
            }}
          />
        ) : null}
        <span
          className={cn(
            'pointer-events-none absolute truncate text-xs whitespace-nowrap',
            done ? 'text-muted line-through' : overdue ? 'text-crit' : 'text-ink-2',
          )}
          style={{ left: labelLeft, top: 0, lineHeight: `${ROW_HEIGHT}px`, maxWidth: 260 }}
          aria-hidden
        >
          {task.title}
          {task.subtask_count ? (
            <span className="ml-1.5 text-muted-2 tabular-nums">
              ↳ {task.completed_subtask_count}/{task.subtask_count}
            </span>
          ) : null}
        </span>
      </div>
    </div>
  );
});

function HoverCard({
  hover,
  critical,
  conflict,
  person,
}: {
  hover: Hover;
  critical: boolean;
  conflict: boolean;
  person: Person | undefined;
}) {
  const { task, span } = hover;
  const done = !!task.completed_at;
  const overdue = !done && span.end < toISODate(new Date());
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-40 w-64 rounded-lg border border-hairline bg-surface p-3 text-sm shadow-pop"
      style={{ left: Math.max(LEFT + 8, hover.x), top: hover.y + ROW_HEIGHT + 4 }}
    >
      <p className="font-mono text-[11px] text-muted-2">{task.key}</p>
      <p className="font-medium">{task.title}</p>
      <p className="mt-1 text-muted">
        {task.type === 'milestone' ? `Milestone · ${fmt(span.end)}` : rangeText(span)}
      </p>
      {person ? <p className="text-muted">{person.name}</p> : <p className="text-muted-2">Unassigned</p>}
      <div className="mt-1.5 flex flex-wrap gap-1 text-xs">
        {done ? <span className="rounded bg-ok-tint px-1.5 text-ok">Done</span> : null}
        {overdue ? <span className="rounded bg-crit-tint px-1.5 text-crit">Overdue</span> : null}
        {critical ? <span className="rounded bg-accent-tint px-1.5">Critical path</span> : null}
        {conflict ? (
          <span className="rounded bg-crit-tint px-1.5 text-crit">Starts before its blocker is due</span>
        ) : null}
      </div>
    </div>
  );
}

function UnscheduledTray({
  tasks,
  canEdit,
  onOpen,
  onDragStart,
}: {
  tasks: Task[];
  canEdit: boolean;
  onOpen: (id: string) => void;
  onDragStart: (task: Task, clientX: number, clientY: number) => void;
}) {
  return (
    <aside aria-label="Unscheduled" className="hidden w-56 shrink-0 flex-col lg:flex">
      <h3 className="mb-2 text-sm font-medium">
        Unscheduled <span className="text-muted-2 tabular-nums">{tasks.length}</span>
      </h3>
      {tasks.length ? (
        <ul className="min-h-0 flex-1 space-y-1 overflow-auto">
          {tasks.map((t) => (
            <li key={t.id} aria-label={t.title}>
              <button
                type="button"
                onClick={() => onOpen(t.id)}
                onPointerDown={(e) => {
                  if (!canEdit || e.button !== 0) return;
                  e.preventDefault();
                  onDragStart(t, e.clientX, e.clientY);
                }}
                title={canEdit ? 'Drag onto the timeline to schedule' : undefined}
                className={cn(
                  'w-full touch-none truncate rounded-md border border-hairline bg-surface px-2 py-1.5 text-left text-sm hover:bg-surface-2',
                  canEdit && 'cursor-grab',
                )}
              >
                {t.title}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-2">Everything has a date.</p>
      )}
    </aside>
  );
}
