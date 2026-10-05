import type { Field, FieldType } from './queries';

/**
 * S7.4.1: filtering, sorting and grouping tasks by custom fields. The same rules as the API's
 * `domain/fields/filters.py`, applied here to tasks already on screen (project lists, board,
 * calendar, My Tasks). A filter travels as text, `<field id>:<op>[:<argument>]`:
 *
 * - `any:<a>,<b>`: option ids (select), user ids (people), `true`/`false` (checkbox); `none` = no value
 * - `min:<x>` / `max:<x>`: a number, or `YYYY-MM-DD` for a date (inclusive)
 * - `has:<text>`: text and URL fields containing it (any case)
 * - `set` / `empty`: has a value / has none
 */
export type FieldOp = 'any' | 'min' | 'max' | 'has' | 'set' | 'empty';
export interface FieldFilter {
  fieldId: string;
  op: FieldOp;
  values: string[]; // for `any`
  value: string | null; // for `min`, `max`, `has`
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const NUMERIC: readonly FieldType[] = ['number', 'currency', 'percent'];
export const LISTED: readonly FieldType[] = ['single_select', 'multi_select', 'people'];
/** Fields a list can be grouped by (one group per option / person / checked state). */
export const GROUPABLE: readonly FieldType[] = ['single_select', 'multi_select', 'people', 'checkbox'];
/** A list groups by single-valued fields only: a task appears once (charts split multi-values too). */
export const LIST_GROUPABLE: readonly FieldType[] = ['single_select', 'checkbox'];
export const MAX_FIELD_FILTERS = 10;

/** Text → filter, or null when it isn't one (URLs are user-editable: bad ones are dropped). */
export function parseFieldFilter(text: string): FieldFilter | null {
  const first = text.indexOf(':');
  if (first < 0) return null;
  const fieldId = text.slice(0, first);
  if (!UUID.test(fieldId)) return null;
  const rest = text.slice(first + 1);
  const second = rest.indexOf(':');
  const op = second < 0 ? rest : rest.slice(0, second);
  const arg = second < 0 ? '' : rest.slice(second + 1);
  if (op === 'any') {
    const values = arg.split(',').filter(Boolean);
    return values.length ? { fieldId, op, values, value: null } : null;
  }
  if (op === 'set' || op === 'empty') return second < 0 ? { fieldId, op, values: [], value: null } : null;
  if ((op === 'min' || op === 'max' || op === 'has') && arg.trim())
    return { fieldId, op, values: [], value: arg };
  return null;
}

export function fieldFilterText(f: FieldFilter): string {
  if (f.op === 'any') return `${f.fieldId}:any:${f.values.join(',')}`;
  if (f.op === 'set' || f.op === 'empty') return `${f.fieldId}:${f.op}`;
  return `${f.fieldId}:${f.op}:${f.value ?? ''}`;
}

const isEmpty = (v: unknown) => v === null || v === undefined || (Array.isArray(v) && v.length === 0);

/** Does a task's value for the filter's field pass it? (`value` undefined = no value.) */
export function fieldMatches(f: FieldFilter, type: FieldType, value: unknown): boolean {
  const empty = isEmpty(value);
  switch (f.op) {
    case 'set':
      return !empty;
    case 'empty':
      return empty;
    case 'any': {
      if (type === 'checkbox') {
        const checked = value === true;
        return f.values.some((v) =>
          v === 'true' ? checked : v === 'false' || v === 'none' ? !checked : false,
        );
      }
      if (empty) return f.values.includes('none');
      const held = Array.isArray(value) ? value.map(String) : [String(value)];
      return f.values.some((v) => held.includes(v));
    }
    case 'min':
    case 'max': {
      if (empty) return false;
      const bound = f.value ?? '';
      if (NUMERIC.includes(type)) {
        const n = Number(bound);
        if (typeof value !== 'number' || !Number.isFinite(n)) return false;
        return f.op === 'min' ? value >= n : value <= n;
      }
      if (type === 'date' && typeof value === 'string')
        return f.op === 'min' ? value >= bound : value <= bound;
      return false;
    }
    case 'has':
      return typeof value === 'string' && value.toLowerCase().includes((f.value ?? '').toLowerCase());
  }
}

/** All filters (AND) against one task's values. Filters on fields not in `fields` are ignored. */
export function matchesFieldFilters(
  filters: readonly FieldFilter[],
  fields: ReadonlyMap<string, Field>,
  values: ReadonlyMap<string, unknown> | undefined,
): boolean {
  return filters.every((f) => {
    const field = fields.get(f.fieldId);
    return !field || fieldMatches(f, field.type, values?.get(f.fieldId));
  });
}

/** Sort keys: comparable values, nulls last (the caller keeps manual order for ties). */
export function fieldSortValue(field: Field, value: unknown): string | number | null {
  if (isEmpty(value)) return null;
  if (NUMERIC.includes(field.type) && typeof value === 'number') return value;
  if (field.type === 'checkbox') return value === true ? 0 : null;
  if (field.type === 'single_select' || field.type === 'multi_select') {
    const options = Array.isArray(field.options) ? field.options : [];
    const first = Array.isArray(value) ? value[0] : value;
    const i = options.findIndex((o) => o.id === first);
    return i < 0 ? null : i; // option order, as the field lists them
  }
  if (Array.isArray(value)) return value.map(String).join(',');
  return String(value);
}

/** The group keys a value puts a task in (several for multi-select and people; `none` when empty). */
export function fieldGroupKeys(field: Field, value: unknown): string[] {
  if (field.type === 'checkbox') return [value === true ? 'true' : 'none'];
  if (isEmpty(value)) return ['none'];
  return Array.isArray(value) ? value.map(String) : [String(value)];
}

/** Readable words for a filter ("Stage: Ship, Plan", "Points ≥ 3"), for chips and descriptions. */
export function describeFieldFilter(
  f: FieldFilter,
  field: Field | undefined,
  personName: (id: string) => string | undefined,
): string {
  const name = field?.name ?? 'A removed field';
  const options = field && Array.isArray(field.options) ? field.options : [];
  const word = (v: string) =>
    v === 'none'
      ? 'No value'
      : v === 'true'
        ? 'Checked'
        : v === 'false'
          ? 'Not checked'
          : (options.find((o) => o.id === v)?.label ?? personName(v) ?? 'Unknown');
  switch (f.op) {
    case 'any':
      return `${name}: ${f.values.map(word).join(', ')}`;
    case 'min':
      return `${name} ≥ ${f.value}`;
    case 'max':
      return `${name} ≤ ${f.value}`;
    case 'has':
      return `${name} contains “${f.value}”`;
    case 'set':
      return `${name} is set`;
    case 'empty':
      return `${name} is empty`;
  }
}
