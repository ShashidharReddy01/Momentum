import { addDays, dayDiff, fromISODate, toISODate } from '@/lib/dates';

/** The pure geometry of the timeline (S6.1.1a): no React, so it can be tested and memoized. */

export type Zoom = 'week' | 'month' | 'quarter';

/** Pixels per day at each zoom. Week shows single days; quarter fits ~6 months on a laptop. */
export const DAY_WIDTH: Record<Zoom, number> = { week: 40, month: 16, quarter: 5 };
export const ZOOMS: Zoom[] = ['week', 'month', 'quarter'];
export const ROW_HEIGHT = 36;

export interface DatedTask {
  id: string;
  type: string;
  start_on: string | null;
  due_on: string | null;
  completed_at: string | null;
  section_id: string | null;
}

/** A task's span on the timeline, or null for the Unscheduled tray. A due-only (or start-only)
 * task is a one-day bar; a milestone is a point on its due date. Start after due (which the API
 * refuses, but old data may hold) is drawn from due to due rather than backwards. */
export function spanOf(t: DatedTask): { start: string; end: string } | null {
  if (t.type === 'milestone') {
    const at = t.due_on ?? t.start_on;
    return at ? { start: at, end: at } : null;
  }
  if (t.start_on && t.due_on)
    return t.start_on <= t.due_on ? { start: t.start_on, end: t.due_on } : { start: t.due_on, end: t.due_on };
  const one = t.due_on ?? t.start_on;
  return one ? { start: one, end: one } : null;
}

/** Monday on or before `d`. */
export const mondayOf = (d: Date) => addDays(d, -((d.getDay() + 6) % 7));

/** The visible date range: every bar plus today, padded, starting on a Monday (so the weekend
 * stripes line up) and at least ~4 months wide so a young project still has room to plan. */
export function rangeOf(spans: { start: string; end: string }[], today: Date): { start: Date; days: number } {
  let lo = addDays(today, -14);
  let hi = addDays(today, 90);
  for (const s of spans) {
    const a = fromISODate(s.start);
    const b = fromISODate(s.end);
    if (a < lo) lo = a;
    if (b > hi) hi = b;
  }
  const start = mondayOf(addDays(lo, -14));
  const end = addDays(hi, 28);
  return { start, days: dayDiff(start, end) + 1 };
}

export const xOf = (rangeStart: Date, iso: string, dayWidth: number) =>
  dayDiff(rangeStart, fromISODate(iso)) * dayWidth;

export interface Ticks {
  /** Upper band: months (or quarters when zoomed out). */
  major: { x: number; width: number; label: string }[];
  /** Lower band: days, week starts, or months. */
  minor: { x: number; label: string; weekend?: boolean; today?: boolean }[];
}

const MONTH = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' });
const MONTH_SHORT = new Intl.DateTimeFormat(undefined, { month: 'short' });

export function ticksOf(rangeStart: Date, days: number, zoom: Zoom, today: Date): Ticks {
  const dw = DAY_WIDTH[zoom];
  const todayIso = toISODate(today);
  const major: Ticks['major'] = [];
  const minor: Ticks['minor'] = [];
  const end = addDays(rangeStart, days);
  // majors: calendar months (quarter zoom: calendar quarters)
  let m = new Date(rangeStart.getFullYear(), rangeStart.getMonth(), 1);
  while (m < end) {
    const step = zoom === 'quarter' ? 3 - (m.getMonth() % 3) : 1;
    const next = new Date(m.getFullYear(), m.getMonth() + step, 1);
    const a = Math.max(0, dayDiff(rangeStart, m));
    const b = Math.min(days, dayDiff(rangeStart, next));
    const label =
      zoom === 'quarter' ? `Q${Math.floor(m.getMonth() / 3) + 1} ${m.getFullYear()}` : MONTH.format(m);
    if (b > a) major.push({ x: a * dw, width: (b - a) * dw, label });
    m = next;
  }
  for (let i = 0; i < days; i++) {
    const d = addDays(rangeStart, i);
    const iso = toISODate(d);
    if (zoom === 'week') {
      minor.push({
        x: i * dw,
        label: String(d.getDate()),
        weekend: d.getDay() === 0 || d.getDay() === 6,
        today: iso === todayIso,
      });
    } else if (zoom === 'month' && d.getDay() === 1) {
      minor.push({ x: i * dw, label: String(d.getDate()) });
    } else if (zoom === 'quarter' && d.getDate() === 1) {
      minor.push({ x: i * dw, label: MONTH_SHORT.format(d) });
    }
  }
  return { major, minor };
}

export type Row<T> =
  | { kind: 'section'; id: string; name: string; count: number; collapsed: boolean }
  | { kind: 'task'; task: T; span: { start: string; end: string } };

/** Rows in section order: a header per section, then its scheduled tasks (in list order) unless
 * the section is collapsed. Unscheduled tasks go to the tray instead. */
export function rowsOf<T extends DatedTask>(
  sections: { id: string; name: string }[],
  tasks: T[],
  collapsed: ReadonlySet<string>,
): { rows: Row<T>[]; unscheduled: T[] } {
  const bySection = new Map<string, T[]>();
  const unscheduled: T[] = [];
  for (const t of tasks) {
    if (!spanOf(t)) {
      unscheduled.push(t);
      continue;
    }
    const key = t.section_id ?? '';
    const list = bySection.get(key);
    if (list) list.push(t);
    else bySection.set(key, [t]);
  }
  const rows: Row<T>[] = [];
  for (const s of sections) {
    const list = bySection.get(s.id) ?? [];
    const isCollapsed = collapsed.has(s.id);
    rows.push({ kind: 'section', id: s.id, name: s.name, count: list.length, collapsed: isCollapsed });
    if (!isCollapsed) for (const t of list) rows.push({ kind: 'task', task: t, span: spanOf(t)! });
  }
  return { rows, unscheduled };
}

export interface Edge {
  task_id: string;
  depends_on_id: string;
}

/** Days a span covers, inclusive. */
const lengthOf = (s: { start: string; end: string }) => dayDiff(fromISODate(s.start), fromISODate(s.end)) + 1;

/**
 * The critical path: the chain of open, scheduled tasks linked by dependencies whose total
 * duration is the longest, i.e. the work that sets the project's end date. Returns task ids in
 * order (first blocker first). Ties go to the chain that ends latest. Cycles (which the API
 * refuses) are ignored rather than looping.
 */
export function criticalPath(tasks: DatedTask[], edges: Edge[]): string[] {
  const open = new Map<string, { start: string; end: string }>();
  for (const t of tasks) {
    const s = spanOf(t);
    if (s && !t.completed_at) open.set(t.id, s);
  }
  const blockers = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  for (const id of open.keys()) indeg.set(id, 0);
  for (const e of edges) {
    if (!open.has(e.task_id) || !open.has(e.depends_on_id)) continue;
    (blockers.get(e.task_id) ?? blockers.set(e.task_id, []).get(e.task_id)!).push(e.depends_on_id);
    indeg.set(e.task_id, (indeg.get(e.task_id) ?? 0) + 1);
  }
  if (blockers.size === 0) return [];
  // Kahn's order over "blocker → dependent"
  const dependents = new Map<string, string[]>();
  for (const [task, list] of blockers)
    for (const b of list) (dependents.get(b) ?? dependents.set(b, []).get(b)!).push(task);
  const queue = [...indeg].filter(([, n]) => n === 0).map(([id]) => id);
  const dist = new Map<string, number>();
  const prev = new Map<string, string>();
  for (const id of queue) dist.set(id, lengthOf(open.get(id)!));
  while (queue.length) {
    const id = queue.shift()!;
    for (const next of dependents.get(id) ?? []) {
      const candidate = dist.get(id)! + lengthOf(open.get(next)!);
      if (candidate > (dist.get(next) ?? 0)) {
        dist.set(next, candidate);
        prev.set(next, id);
      }
      const left = indeg.get(next)! - 1;
      indeg.set(next, left);
      if (left === 0) queue.push(next);
    }
  }
  let best: string | null = null;
  for (const [id, d] of dist) {
    if (!prev.has(id) && !dependents.has(id)) continue; // a lone task is not a chain
    const b = best === null ? -1 : dist.get(best)!;
    if (d > b || (d === b && open.get(id)!.end > open.get(best!)!.end)) best = id;
  }
  if (best === null) return [];
  const path = [best];
  while (prev.has(path[0]!)) path.unshift(prev.get(path[0]!)!);
  return path.length > 1 ? path : [];
}

/** Edges where an open dependent starts before its open blocker is due: a schedule that can't
 * work as drawn. Same-day hand-offs are allowed. */
export function conflictsOf(tasks: DatedTask[], edges: Edge[]): Set<string> {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const out = new Set<string>();
  for (const e of edges) {
    const dep = byId.get(e.task_id);
    const blk = byId.get(e.depends_on_id);
    if (!dep || !blk || dep.completed_at || blk.completed_at) continue;
    const ds = spanOf(dep);
    const bs = spanOf(blk);
    if (ds && bs && ds.start < bs.end) out.add(edgeKey(e));
  }
  return out;
}

export const edgeKey = (e: Edge) => `${e.depends_on_id}>${e.task_id}`;

/** An elbow from the end of the blocker's bar to the start of the dependent's. When the
 * dependent starts too early to go straight across, the path drops between the rows and doubles
 * back, the usual Gantt routing. */
export function arrowPath(x1: number, y1: number, x2: number, y2: number): string {
  const gap = 8;
  if (x2 - x1 >= gap * 2) return `M${x1},${y1} H${x1 + gap} V${y2} H${x2}`;
  const mid = y1 + (y2 > y1 ? ROW_HEIGHT / 2 : -ROW_HEIGHT / 2);
  return `M${x1},${y1} H${x1 + gap} V${mid} H${x2 - gap} V${y2} H${x2}`;
}
