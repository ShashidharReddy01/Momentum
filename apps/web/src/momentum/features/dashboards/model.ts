import { fieldFilterText, parseFieldFilter, type FieldFilter } from '@/features/fields';
import type { GroupRow, QueryResult, QuerySpec, SeriesPoint, WidgetKind } from './queries';

/**
 * Chart colour, by the job it does (design-system.md "Charts"):
 * - **state** (`group_by: status`) uses the reserved status tokens, always with a label;
 * - **identity with its own colour** (projects, tags, field options) keeps that colour, so a
 *   project is the same colour here as on its chip;
 * - **other identities** (people, sections) take `--chart-1…8` in a fixed order, never cycled:
 *   past eight, the rest share the "Other" grey;
 * - a bar chart of one series is one colour (`--chart-1`), because bar length already carries
 *   the value.
 */
const STATUS_COLOR: Record<string, string> = {
  overdue: 'var(--crit)',
  due_soon: 'var(--warn)',
  later: 'var(--info)',
  no_date: 'var(--muted-2)',
  completed: 'var(--ok)',
};
const PRIORITY_COLOR: Record<string, string> = {
  urgent: 'var(--crit)',
  high: 'var(--warn)',
  medium: 'var(--info)',
  low: 'var(--muted)',
  none: 'var(--hairline)',
};
export const OTHER_COLOR = 'var(--muted-2)';
export const SERIES_COLOR = 'var(--chart-1)';
const SLOTS = 8;

/** A stored colour: a palette token (`proj-6`) or a hex value (tags, field options). */
export function tokenColor(c: string | null | undefined): string | null {
  if (!c) return null;
  return c.startsWith('#') ? c : `var(--${c})`;
}

export function colorOf(
  spec: Pick<QuerySpec, 'group_by'>,
  group: GroupRow,
  index: number,
  kind: WidgetKind,
): string {
  if (group.key === 'other') return OTHER_COLOR;
  if (spec.group_by === 'status') return STATUS_COLOR[group.key] ?? OTHER_COLOR;
  if (spec.group_by === 'priority') return PRIORITY_COLOR[group.key] ?? OTHER_COLOR;
  if (group.key === 'none') return 'var(--hairline)';
  const own = tokenColor(group.color);
  if (own) return own;
  if (kind === 'bar') return SERIES_COLOR;
  return index < SLOTS ? `var(--chart-${index + 1})` : OTHER_COLOR;
}

/** Minutes as hours ("12.5h"), counts as whole numbers with separators, a field's numbers with up
 * to two decimals (S7.4.1: totals and averages of number fields). */
export function formatValue(result: Pick<QueryResult, 'measure'>, value: number): string {
  if (result.measure === 'sum_estimate') {
    const h = value / 60;
    return `${h >= 100 ? Math.round(h).toLocaleString() : Math.round(h * 10) / 10}h`;
  }
  if (result.measure === 'sum_field' || result.measure === 'avg_field')
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return Math.round(value).toLocaleString();
}

/** An average keeps one decimal below 10, so 0.2 a week doesn't read as nothing. */
export function formatAverage(result: Pick<QueryResult, 'measure'>, value: number): string {
  if (result.measure === 'sum_estimate' || value >= 10) return formatValue(result, value);
  return (Math.round(value * 10) / 10).toLocaleString();
}

export function unitOf(
  result: Pick<QueryResult, 'measure'> & { measure_field_name?: string | null },
  value: number,
): string {
  if (result.measure === 'sum_estimate') return 'estimated';
  if (result.measure === 'sum_field') return `total ${result.measure_field_name ?? ''}`.trim();
  if (result.measure === 'avg_field') return `average ${result.measure_field_name ?? ''}`.trim();
  return value === 1 ? 'task' : 'tasks';
}

export function share(value: number, total: number): string {
  if (!total) return '0%';
  const p = (value / total) * 100;
  return p > 0 && p < 1 ? '<1%' : `${Math.round(p)}%`;
}

/** "Sep 7" for a bucket start (a YYYY-MM-DD date, read as a local date). */
export function bucketLabel(iso: string, bucket: QuerySpec['time_bucket']): string {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y!, m! - 1, d!);
  if (bucket === 'month') return date.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** The line chart's one-line headline: the latest bucket against the average of the ones before
 * it (only buckets that have finished count toward the average). */
export function seriesHeadline(points: SeriesPoint[]): { latest: number; average: number | null } {
  if (!points.length) return { latest: 0, average: null };
  const latest = points[points.length - 1]!.value;
  const before = points.slice(0, -1);
  if (!before.length) return { latest, average: null };
  const average = before.reduce((a, p) => a + p.value, 0) / before.length;
  return { latest, average: Math.round(average * 10) / 10 };
}

/** Count tiles that are about late work read in the critical tone when non-zero. */
export function isAlarm(spec: Pick<QuerySpec, 'filters'>, value: number | null | undefined): boolean {
  return !!value && !!spec.filters?.overdue;
}

export const KIND_LABELS: Record<WidgetKind, string> = {
  count: 'Number',
  bar: 'Bar chart',
  donut: 'Donut',
  line: 'Trend line',
  list: 'Task list',
};

export const GROUP_LABELS: Record<NonNullable<QuerySpec['group_by']>, string> = {
  assignee: 'Assignee',
  status: 'Due date (overdue, soon, later…)',
  priority: 'Priority',
  section: 'Section',
  project: 'Project',
  tag: 'Tag',
  field: 'Custom field',
};

// ---------- the add/edit chart form ----------

type GroupBy = NonNullable<QuerySpec['group_by']>;
type TimeField = NonNullable<QuerySpec['time_field']>;
type Bucket = NonNullable<QuerySpec['time_bucket']>;
type Filters = NonNullable<QuerySpec['filters']>;
type Status = Filters['status'];

/** A complete v1 spec from the parts that matter (the API's shape carries every default). */
export function fullSpec(
  parts: Partial<Omit<QuerySpec, 'filters'>> & { filters?: Partial<Filters> },
): QuerySpec {
  return {
    version: 1,
    entity: 'tasks',
    measure: 'count',
    time_field: 'completed',
    window_days: 84,
    limit: 8,
    ...parts,
    filters: { status: 'open', overdue: false, blocked: false, ...parts.filters },
  };
}

/** Filters the form has no control for (projects, sections, tags, priorities, named people, a
 * due-date range). A chart drafted by Mo or saved through the API can carry them; the editor
 * keeps them, shows each as a removable chip, and never drops one silently. */
export interface Narrow {
  project_ids?: string[];
  section_ids?: string[];
  tag_ids?: string[];
  priorities?: NonNullable<Filters['priorities']>;
  /** assignees other than exactly "me" (the form's own chip) */
  assignees?: string[];
  due_from?: string | null;
  due_to?: string | null;
}
export type NarrowKey = keyof Narrow;

/** The editor's state: plain choices, turned into a spec that is valid by construction. */
export interface Draft {
  kind: WidgetKind;
  title: string;
  titleTouched: boolean;
  status: Status;
  overdue: boolean;
  blocked: boolean;
  mine: boolean;
  dueWithin: number | null;
  completedWithin: number | null;
  groupBy: GroupBy;
  fieldId: string | null;
  timeField: TimeField;
  bucket: Bucket;
  windowDays: number;
  measure: QuerySpec['measure'];
  /** S7.4.1: the number field a sum/average adds up, the date field a line counts by, and
   * custom-field filters (`<field id>:<op>[:<arg>]`, as the lists keep them) */
  measureFieldId: string | null;
  timeFieldId: string | null;
  fieldFilters: string[];
  limit: number;
  size: 'sm' | 'md' | 'lg';
  narrow: Narrow;
}

export const DEFAULT_SIZE: Record<WidgetKind, Draft['size']> = {
  count: 'sm',
  bar: 'md',
  donut: 'md',
  line: 'md',
  list: 'lg',
};

export function newDraft(kind: WidgetKind = 'bar'): Draft {
  return {
    kind,
    title: '',
    titleTouched: false,
    status: 'open',
    overdue: false,
    blocked: false,
    mine: false,
    dueWithin: null,
    completedWithin: null,
    groupBy: 'assignee',
    fieldId: null,
    timeField: 'completed',
    bucket: 'week',
    windowDays: 84,
    measure: 'count',
    measureFieldId: null,
    timeFieldId: null,
    fieldFilters: [],
    limit: kind === 'list' ? 10 : 8,
    size: DEFAULT_SIZE[kind],
    narrow: {},
  };
}

function narrowOf(f: Partial<Filters>): Narrow {
  const n: Narrow = {};
  if (f.project_ids?.length) n.project_ids = [...f.project_ids];
  if (f.section_ids?.length) n.section_ids = [...f.section_ids];
  if (f.tag_ids?.length) n.tag_ids = [...f.tag_ids];
  if (f.priorities?.length) n.priorities = [...f.priorities];
  const a = f.assignees ?? [];
  if (a.length && !(a.length === 1 && a[0] === 'me')) n.assignees = [...a];
  if (f.due_from) n.due_from = f.due_from;
  if (f.due_to) n.due_to = f.due_to;
  return n;
}

/** The draft without one narrowing value (`value` omitted: the whole filter, e.g. a date range). */
export function withoutNarrow(d: Draft, key: NarrowKey, value?: string): Draft {
  const narrow = { ...d.narrow };
  if (key === 'due_from' || key === 'due_to' || value === undefined) {
    delete narrow[key];
  } else {
    const left = ((narrow[key] as string[] | undefined) ?? []).filter((v) => v !== value);
    if (left.length) (narrow as Record<string, string[]>)[key] = left;
    else delete narrow[key];
  }
  return { ...d, narrow };
}

export function draftOf(item: {
  kind: WidgetKind;
  title: string;
  spec: QuerySpec;
  size: Draft['size'];
}): Draft {
  const s = item.spec;
  const f: Partial<Filters> = s.filters ?? {};
  return {
    ...newDraft(item.kind),
    title: item.title,
    titleTouched: true,
    status: f.status ?? 'open',
    overdue: !!f.overdue,
    blocked: !!f.blocked,
    mine: (f.assignees ?? []).length === 1 && f.assignees![0] === 'me',
    dueWithin: f.due_within_days ?? null,
    completedWithin: f.completed_within_days ?? null,
    groupBy: s.group_by ?? 'assignee',
    fieldId: s.field_id ?? null,
    timeField: s.time_field ?? 'completed',
    bucket: s.time_bucket ?? 'week',
    windowDays: s.window_days ?? 84,
    measure: s.measure ?? 'count',
    measureFieldId: s.measure_field_id ?? null,
    timeFieldId: s.time_field_id ?? null,
    fieldFilters: (f.fields ?? []).map((x) =>
      fieldFilterText({ fieldId: x.field_id, op: x.op, values: x.values ?? [], value: x.value ?? null }),
    ),
    limit: s.limit ?? (item.kind === 'list' ? 10 : 8),
    size: item.size,
    narrow: narrowOf(f),
  };
}

/** The spec a draft stands for. Choices that don't apply to the kind are dropped, and choices
 * that contradict each other are resolved the way the reader would expect (a completed-over-time
 * line counts completed work; "overdue" means open work). */
export function specOf(d: Draft): QuerySpec {
  let status = d.status;
  if (d.kind === 'line' && d.timeField === 'completed' && status === 'open') status = 'completed';
  if ((d.overdue || d.blocked) && status === 'completed') status = 'open';
  const filters: Filters = { status, overdue: d.overdue, blocked: d.blocked };
  const n = d.narrow;
  if (n.project_ids?.length) filters.project_ids = n.project_ids;
  if (n.section_ids?.length) filters.section_ids = n.section_ids;
  if (n.tag_ids?.length) filters.tag_ids = n.tag_ids;
  if (n.priorities?.length) filters.priorities = n.priorities;
  if (n.due_from) filters.due_from = n.due_from;
  if (n.due_to) filters.due_to = n.due_to;
  if (d.mine) filters.assignees = ['me'];
  else if (n.assignees?.length) filters.assignees = n.assignees;
  if (d.dueWithin !== null && !d.overdue) filters.due_within_days = d.dueWithin;
  if (d.completedWithin !== null && status !== 'open') filters.completed_within_days = d.completedWithin;
  const parsed = d.fieldFilters.map(parseFieldFilter).filter((x): x is FieldFilter => x !== null);
  if (parsed.length)
    filters.fields = parsed.map((x) => ({
      field_id: x.fieldId,
      op: x.op,
      values: x.values,
      value: x.value,
    }));
  const fieldMeasure = d.measure === 'sum_field' || d.measure === 'avg_field';
  const measure = d.kind === 'list' || (fieldMeasure && !d.measureFieldId) ? 'count' : d.measure;
  const spec = fullSpec({ filters, measure });
  if (measure === 'sum_field' || measure === 'avg_field') spec.measure_field_id = d.measureFieldId;
  if (d.kind === 'bar' || d.kind === 'donut') {
    spec.group_by = d.groupBy;
    if (d.groupBy === 'field') spec.field_id = d.fieldId;
    spec.limit = d.limit;
  } else if (d.kind === 'line') {
    spec.time_bucket = d.bucket;
    spec.time_field = d.timeField === 'field' && !d.timeFieldId ? 'completed' : d.timeField;
    if (spec.time_field === 'field') spec.time_field_id = d.timeFieldId;
    spec.window_days = d.windowDays;
  } else if (d.kind === 'list') {
    spec.limit = d.limit;
  }
  return spec;
}

/** Why a draft can't be saved yet, or null. */
export function draftProblem(d: Draft): string | null {
  if ((d.kind === 'bar' || d.kind === 'donut') && d.groupBy === 'field' && !d.fieldId)
    return 'Pick a custom field to group by.';
  if (d.kind !== 'list' && (d.measure === 'sum_field' || d.measure === 'avg_field') && !d.measureFieldId)
    return 'Pick the number field to add up.';
  if (d.kind === 'line' && d.timeField === 'field' && !d.timeFieldId)
    return 'Pick the date field to count by.';
  if (!(d.titleTouched ? d.title : autoTitle(d)).trim()) return 'Give the chart a title.';
  return null;
}

/** A readable default title from the choices ("Open tasks by assignee"). */
export function autoTitle(
  d: Draft,
  fieldName?: string | null,
  names: { measure?: string | null; time?: string | null } = {},
): string {
  const s = specOf(d);
  const f = s.filters!;
  let what = f.overdue
    ? 'Overdue tasks'
    : f.blocked
      ? 'Blocked tasks'
      : { open: 'Open tasks', completed: 'Completed tasks', all: 'Tasks' }[f.status ?? 'open'];
  if (s.measure === 'sum_estimate') what = `Estimated hours (${what.toLowerCase()})`;
  if (s.measure === 'sum_field') what = `Total ${names.measure ?? 'value'} (${what.toLowerCase()})`;
  if (s.measure === 'avg_field') what = `Average ${names.measure ?? 'value'} (${what.toLowerCase()})`;
  if (d.mine) what = `My ${what.toLowerCase()}`;
  if (d.kind === 'line') {
    const verb = {
      completed: 'Completed',
      created: 'Created',
      due: 'Due',
      field: `By ${names.time ?? 'date field'}`,
    }[d.timeField];
    return `${verb} per ${d.bucket}`;
  }
  if (d.kind === 'bar' || d.kind === 'donut') {
    const by =
      d.groupBy === 'field' ? (fieldName ?? 'field') : d.groupBy === 'status' ? 'due date' : d.groupBy;
    return `${what} by ${by}`;
  }
  if (f.due_within_days != null) return `${what} due in ${f.due_within_days} days`;
  return what;
}
