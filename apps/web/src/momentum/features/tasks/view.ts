import type { Field } from '@/features/fields';
import {
  fieldGroupKeys,
  fieldSortValue,
  matchesFieldFilters,
  MAX_FIELD_FILTERS,
  parseFieldFilter,
  type FieldFilter,
} from '@/features/fields';
import { dayDiff, fromISODate, toISODate } from '@/lib/dates';
import type { Task } from './queries';

/** How a project's list is filtered, sorted and grouped (URL params ⇄ saved prefs). Pure. */
export type DueFilter = 'any' | 'overdue' | 'today' | 'this_week' | 'next_week' | 'no_date';
/** S7.4.1: `field:<id>` sorts or groups by a custom field. */
export type FieldKey = `field:${string}`;
export type SortKey = 'manual' | 'due' | 'assignee' | 'created' | 'title' | FieldKey;
export type GroupKey = 'section' | 'assignee' | 'due' | FieldKey;

export interface ListView {
  assignees: string[]; // user ids, 'me', 'none'
  tags: string[]; // tag ids, OR-ed like assignees
  due: DueFilter;
  show_completed: boolean;
  sort: SortKey;
  group: GroupKey;
  fields: string[]; // S7.4.1: custom-field filters, `<field id>:<op>[:<arg>]`, AND-ed
}

export const DEFAULT_VIEW: ListView = {
  assignees: [],
  tags: [],
  due: 'any',
  show_completed: false,
  sort: 'manual',
  group: 'section',
  fields: [],
};

const DUE: readonly DueFilter[] = ['any', 'overdue', 'today', 'this_week', 'next_week', 'no_date'];
const SORT: readonly SortKey[] = ['manual', 'due', 'assignee', 'created', 'title'];
const GROUP: readonly GroupKey[] = ['section', 'assignee', 'due'];
const TOKEN = /^(me|none|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const VIEW_PARAMS = ['assignee', 'tag', 'due', 'completed', 'sort', 'group', 'field'];
const FIELD_KEY = /^field:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const isFieldKey = (k: string): k is FieldKey => FIELD_KEY.test(k);
export const isSortKey = (k: string | undefined): k is SortKey =>
  !!k && ((SORT as readonly string[]).includes(k) || isFieldKey(k));
export const isGroupKey = (k: string | undefined): k is GroupKey =>
  !!k && ((GROUP as readonly string[]).includes(k) || isFieldKey(k));
export const fieldIdOf = (k: string): string | null => (isFieldKey(k) ? k.slice(6) : null);
/** The view's field filters, parsed (malformed ones dropped). */
export const fieldFiltersOf = (v: ListView): FieldFilter[] =>
  v.fields.map(parseFieldFilter).filter((f): f is FieldFilter => f !== null);
/** Does the view need custom-field values (to filter, sort or group)? */
export const usesFields = (v: ListView) => v.fields.length > 0 || isFieldKey(v.sort) || isFieldKey(v.group);

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
    v && ((allowed as readonly string[]).includes(v) || isFieldKey(v)) ? (v as T) : fallback;
  return {
    assignees: [...new Set(params.getAll('assignee').filter((a) => TOKEN.test(a)))].slice(0, 50),
    tags: [...new Set(params.getAll('tag').filter((t) => UUID.test(t)))].slice(0, 50),
    due: pick(params.get('due'), DUE, 'any'),
    show_completed: params.get('completed') === '1',
    sort: pick(params.get('sort'), SORT, 'manual'),
    group: pick(params.get('group'), GROUP, 'section'),
    fields: [...new Set(params.getAll('field').filter((f) => parseFieldFilter(f) !== null))].slice(
      0,
      MAX_FIELD_FILTERS,
    ),
  };
}

/** Write a view into URL params (defaults omitted; unrelated params such as ?task= kept). */
export function viewToParams(view: ListView, current: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(current);
  VIEW_PARAMS.forEach((k) => next.delete(k));
  view.assignees.forEach((a) => next.append('assignee', a));
  view.tags.forEach((t) => next.append('tag', t));
  if (view.due !== 'any') next.set('due', view.due);
  if (view.show_completed) next.set('completed', '1');
  if (view.sort !== 'manual') next.set('sort', view.sort);
  if (view.group !== 'section') next.set('group', view.group);
  view.fields.forEach((f) => next.append('field', f));
  return next;
}

export const isDefaultView = (v: ListView) =>
  v.assignees.length === 0 &&
  v.tags.length === 0 &&
  v.due === 'any' &&
  !v.show_completed &&
  v.sort === 'manual' &&
  v.group === 'section' &&
  v.fields.length === 0;
export const filterCount = (v: ListView) =>
  (v.assignees.length ? 1 : 0) + (v.tags.length ? 1 : 0) + (v.due !== 'any' ? 1 : 0) + v.fields.length;

/** Custom fields and each task's values, for filtering, sorting and grouping by them. */
export interface FieldContext {
  fields: ReadonlyMap<string, Field>;
  valuesOf: (taskId: string) => ReadonlyMap<string, unknown> | undefined;
}
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

export function matches(
  task: Task,
  view: ListView,
  meId: string | undefined,
  today: Date,
  taskTagIds?: ReadonlySet<string>,
  fieldCtx?: FieldContext,
): boolean {
  if (view.fields.length && fieldCtx) {
    if (!matchesFieldFilters(fieldFiltersOf(view), fieldCtx.fields, fieldCtx.valuesOf(task.id))) return false;
  }
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
  if (view.tags.length) {
    if (!view.tags.some((t) => taskTagIds?.has(t))) return false;
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
  fieldCtx?: FieldContext,
): Task[] {
  if (sort === 'manual') return [...tasks];
  const indexed = tasks.map((t, i) => [t, i] as const);
  const sortId = fieldIdOf(sort);
  const sortField = sortId ? fieldCtx?.fields.get(sortId) : undefined;
  const fieldValue = (t: Task) =>
    sortField ? fieldSortValue(sortField, fieldCtx?.valuesOf(t.id)?.get(sortField.id)) : null;
  const cmp = (a: Task, b: Task): number => {
    if (isFieldKey(sort)) {
      const x = fieldValue(a);
      const y = fieldValue(b);
      if (x === y) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return typeof x === 'number' && typeof y === 'number'
        ? x - y
        : String(x).localeCompare(String(y), undefined, { sensitivity: 'base', numeric: true });
    }
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
  fieldCtx?: FieldContext,
): Group[] {
  if (isFieldKey(group)) return groupByField(tasks, group, nameOf, fieldCtx);
  if (group === 'due') {
    return DUE_GROUPS.map((g) => ({
      ...g,
      tasks: tasks.filter((t) => dueBucket(t.due_on, today) === g.id),
    })).filter((g) => g.tasks.length);
  }
  const map = new Map<string, Task[]>();
  for (const t of tasks) {
    const key = t.assignee_id ?? 'none';
    const list = map.get(key);
    if (list) list.push(t);
    else map.set(key, [t]);
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

/** Groups by a custom field: option order (select), name order (people), checked first; a task with
 * several options or people is in each of their groups; "No value" last. */
function groupByField(
  tasks: readonly Task[],
  group: FieldKey,
  nameOf: (id: string) => string | undefined,
  fieldCtx: FieldContext | undefined,
): Group[] {
  const field = fieldCtx?.fields.get(group.slice(6));
  if (!field) return [{ id: `${group}:none`, name: 'All tasks', tasks: [...tasks] }];
  const map = new Map<string, Task[]>();
  for (const t of tasks) {
    for (const key of fieldGroupKeys(field, fieldCtx?.valuesOf(t.id)?.get(field.id))) {
      const list = map.get(key);
      if (list) list.push(t);
      else map.set(key, [t]);
    }
  }
  const options = Array.isArray(field.options) ? field.options : [];
  const label = (key: string): string => {
    if (key === 'none') return field.type === 'checkbox' ? 'Not checked' : 'No value';
    if (field.type === 'checkbox') return 'Checked';
    if (field.type === 'people') return nameOf(key) ?? 'Unknown person';
    return options.find((o) => o.id === key)?.label ?? 'Removed option';
  };
  const rank = (key: string): number => {
    if (key === 'none') return Number.MAX_SAFE_INTEGER;
    const i = options.findIndex((o) => o.id === key);
    return i < 0 ? options.length : i;
  };
  return [...map.entries()]
    .map(([key, list]) => ({ id: `${group}:${key}`, name: label(key), tasks: list, key }))
    .sort((a, b) => rank(a.key) - rank(b.key) || a.name.localeCompare(b.name))
    .map(({ id, name, tasks: list }) => ({ id, name, tasks: list }));
}
