import { dayDiff, fromISODate, toISODate } from '@/lib/dates';
import type { Task } from './queries';

/** How a project's list is filtered, sorted and grouped (URL params ⇄ saved prefs). Pure. */
export type DueFilter = 'any' | 'overdue' | 'today' | 'this_week' | 'next_week' | 'no_date';
export type SortKey = 'manual' | 'due' | 'assignee' | 'created' | 'title';
export type GroupKey = 'section' | 'assignee' | 'due';

export interface ListView {
  assignees: string[]; // user ids, 'me', 'none'
  due: DueFilter;
  show_completed: boolean;
  sort: SortKey;
  group: GroupKey;
}

export const DEFAULT_VIEW: ListView = {
  assignees: [],
  due: 'any',
  show_completed: false,
  sort: 'manual',
  group: 'section',
};

const DUE: readonly DueFilter[] = ['any', 'overdue', 'today', 'this_week', 'next_week', 'no_date'];
const SORT: readonly SortKey[] = ['manual', 'due', 'assignee', 'created', 'title'];
const GROUP: readonly GroupKey[] = ['section', 'assignee', 'due'];
const TOKEN = /^(me|none|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;
const VIEW_PARAMS = ['assignee', 'due', 'completed', 'sort', 'group'];

export const DUE_LABEL: Record<DueFilter, string> = {
  any: 'Any time',
  overdue: 'Overdue',
  today: 'Due today',
  this_week: 'Due this week',
  next_week: 'Due next week',
  no_date: 'No due date',
};
export const SORT_LABEL: Record<SortKey, string> = {
  manual: 'None (drag order)',
  due: 'Due date',
  assignee: 'Assignee',
  created: 'Creation date',
  title: 'Alphabetical',
};
export const GROUP_LABEL: Record<GroupKey, string> = {
  section: 'Sections',
  assignee: 'Assignee',
  due: 'Due date',
};

/** Read a view from URL params; null when the URL carries no view params. Invalid values are dropped. */
export function viewFromParams(params: URLSearchParams): ListView | null {
  if (!VIEW_PARAMS.some((k) => params.has(k))) return null;
  const pick = <T extends string>(v: string | null, allowed: readonly T[], fallback: T): T =>
    v && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
  return {
    assignees: [...new Set(params.getAll('assignee').filter((a) => TOKEN.test(a)))].slice(0, 50),
    due: pick(params.get('due'), DUE, 'any'),
    show_completed: params.get('completed') === '1',
    sort: pick(params.get('sort'), SORT, 'manual'),
    group: pick(params.get('group'), GROUP, 'section'),
  };
}

/** Write a view into URL params (defaults omitted; unrelated params such as ?task= kept). */
export function viewToParams(view: ListView, current: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(current);
  VIEW_PARAMS.forEach((k) => next.delete(k));
  view.assignees.forEach((a) => next.append('assignee', a));
  if (view.due !== 'any') next.set('due', view.due);
  if (view.show_completed) next.set('completed', '1');
  if (view.sort !== 'manual') next.set('sort', view.sort);
  if (view.group !== 'section') next.set('group', view.group);
  return next;
}

export const isDefaultView = (v: ListView) =>
  v.assignees.length === 0 &&
  v.due === 'any' &&
  !v.show_completed &&
  v.sort === 'manual' &&
  v.group === 'section';
export const filterCount = (v: ListView) => (v.assignees.length ? 1 : 0) + (v.due !== 'any' ? 1 : 0);
/** Manual order is only meaningful (and draggable) when sorted by drag order and grouped by section. */
export const isManualOrder = (v: ListView) => v.sort === 'manual' && v.group === 'section';

export type DueBucket = 'overdue' | 'today' | 'this_week' | 'next_week' | 'later' | 'no_date';

/** Due bucket in local time; weeks start on Monday. */
export function dueBucket(dueOn: string | null, today: Date): DueBucket {
  if (!dueOn) return 'no_date';
  const diff = dayDiff(today, fromISODate(dueOn));
  if (diff < 0) return 'overdue';
  if (diff === 0) return 'today';
  const toSunday = 6 - ((today.getDay() + 6) % 7);
  if (diff <= toSunday) return 'this_week';
  if (diff <= toSunday + 7) return 'next_week';
  return 'later';
}

export function matches(task: Task, view: ListView, meId: string | undefined, today: Date): boolean {
  if (view.assignees.length) {
    const ok = view.assignees.some((a) =>
      a === 'none'
        ? task.assignee_id === null
        : a === 'me'
          ? !!meId && task.assignee_id === meId
          : task.assignee_id === a,
    );
    if (!ok) return false;
  }
  if (view.due !== 'any') {
    const bucket = dueBucket(task.due_on, today);
    // "this week" means today through Sunday (like the API); overdue is its own filter
    if (view.due === 'this_week') return bucket === 'today' || bucket === 'this_week';
    return bucket === view.due;
  }
  return true;
}

const byNullableString = (a: string | null | undefined, b: string | null | undefined) =>
  a === b ? 0 : a == null ? 1 : b == null ? -1 : a.localeCompare(b, undefined, { sensitivity: 'base' });

/** Stable sort of tasks already in manual order; ties keep manual order. Nulls sort last. */
export function sortTasks(
  tasks: readonly Task[],
  sort: SortKey,
  nameOf: (id: string) => string | undefined,
): Task[] {
  if (sort === 'manual') return [...tasks];
  const indexed = tasks.map((t, i) => [t, i] as const);
  const cmp = (a: Task, b: Task): number => {
    switch (sort) {
      case 'due':
        return byNullableString(a.due_on, b.due_on) || byNullableString(a.due_at, b.due_at);
      case 'assignee':
        return byNullableString(
          a.assignee_id ? nameOf(a.assignee_id) : null,
          b.assignee_id ? nameOf(b.assignee_id) : null,
        );
      case 'created':
        return a.created_at.localeCompare(b.created_at);
      case 'title':
        return a.title.localeCompare(b.title, undefined, { sensitivity: 'base', numeric: true });
    }
  };
  return indexed.sort(([a, i], [b, j]) => cmp(a, b) || i - j).map(([t]) => t);
}

export interface Group {
  id: string;
  name: string;
  tasks: Task[];
}

const DUE_GROUPS: { id: DueBucket; name: string }[] = [
  { id: 'overdue', name: 'Overdue' },
  { id: 'today', name: 'Today' },
  { id: 'this_week', name: 'This week' },
  { id: 'next_week', name: 'Next week' },
  { id: 'later', name: 'Later' },
  { id: 'no_date', name: 'No due date' },
];

/** Groups for the non-section groupings (empty groups omitted). Tasks keep their given order. */
export function groupTasks(
  tasks: readonly Task[],
  group: Exclude<GroupKey, 'section'>,
  nameOf: (id: string) => string | undefined,
  meId: string | undefined,
  today: Date,
): Group[] {
  if (group === 'due') {
    return DUE_GROUPS.map((g) => ({
      ...g,
      tasks: tasks.filter((t) => dueBucket(t.due_on, today) === g.id),
    })).filter((g) => g.tasks.length);
  }
  const map = new Map<string, Task[]>();
  for (const t of tasks) {
    const key = t.assignee_id ?? 'none';
    map.set(key, [...(map.get(key) ?? []), t]);
  }
  const label = (id: string) => (id === 'none' ? 'Unassigned' : (nameOf(id) ?? 'Unknown person'));
  return [...map.entries()]
    .map(([id, list]) => ({
      id: `assignee:${id}`,
      name: label(id) + (id === meId ? ' (you)' : ''),
      tasks: list,
    }))
    .sort((a, b) =>
      a.id === 'assignee:none' ? 1 : b.id === 'assignee:none' ? -1 : a.name.localeCompare(b.name),
    );
}

export const todayLocal = () => fromISODate(toISODate(new Date()));
