import { describe, expect, it } from 'vitest';
import {
  describeFieldFilter,
  fieldFilterText,
  fieldGroupKeys,
  fieldMatches,
  fieldSortValue,
  matchesFieldFilters,
  parseFieldFilter,
  type FieldFilter,
} from './filters';
import type { Field } from './queries';

const FID = '01a10bbc-85b8-7013-815b-71c5b6893e6a';
const field = (type: Field['type'], extra: Partial<Field> = {}): Field =>
  ({
    id: FID,
    name: 'Stage',
    type,
    options: null,
    description: null,
    is_library: true,
    ...extra,
  }) as Field;
const f = (op: FieldFilter['op'], values: string[] = [], value: string | null = null): FieldFilter => ({
  fieldId: FID,
  op,
  values,
  value,
});

describe('custom-field filters (S7.4.1, same rules as the API)', () => {
  it('parses and writes the text form, dropping anything malformed', () => {
    for (const text of [`${FID}:any:a,b`, `${FID}:min:3`, `${FID}:has:a:b`, `${FID}:empty`]) {
      expect(fieldFilterText(parseFieldFilter(text)!)).toBe(text);
    }
    expect(parseFieldFilter(`${FID}:has:a:b`)!.value).toBe('a:b');
    for (const bad of ['nope:any:x', `${FID}:like:x`, `${FID}:any:`, `${FID}:min:`, `${FID}:set:x`, FID])
      expect(parseFieldFilter(bad)).toBeNull();
  });

  it('matches every op the way the API does', () => {
    expect(fieldMatches(f('any', ['a']), 'single_select', 'a')).toBe(true);
    expect(fieldMatches(f('any', ['a']), 'single_select', 'b')).toBe(false);
    expect(fieldMatches(f('any', ['none']), 'single_select', undefined)).toBe(true);
    expect(fieldMatches(f('any', ['b']), 'multi_select', ['a', 'b'])).toBe(true);
    expect(fieldMatches(f('any', ['u1']), 'people', ['u1'])).toBe(true);
    expect(fieldMatches(f('any', ['none']), 'people', [])).toBe(true); // an empty list is no value
    expect(fieldMatches(f('any', ['true']), 'checkbox', true)).toBe(true);
    expect(fieldMatches(f('any', ['false']), 'checkbox', undefined)).toBe(true); // never set = unchecked
    expect(fieldMatches(f('min', [], '3'), 'number', 3)).toBe(true);
    expect(fieldMatches(f('max', [], '3'), 'number', 3.5)).toBe(false);
    expect(fieldMatches(f('min', [], '3'), 'number', undefined)).toBe(false);
    expect(fieldMatches(f('min', [], '2030-01-01'), 'date', '2030-01-10')).toBe(true);
    expect(fieldMatches(f('max', [], '2030-01-01'), 'date', '2030-01-10')).toBe(false);
    expect(fieldMatches(f('has', [], '100%'), 'text', 'Needs 100% sign-off')).toBe(true);
    expect(fieldMatches(f('has', [], 'COPY'), 'text', 'copy edit')).toBe(true);
    expect(fieldMatches(f('set'), 'number', 0)).toBe(true); // zero is a value
    expect(fieldMatches(f('empty'), 'text', undefined)).toBe(true);
  });

  it('ANDs filters and ignores ones on fields the project no longer has', () => {
    const fields = new Map([[FID, field('number')]]);
    const values = new Map<string, unknown>([[FID, 5]]);
    expect(matchesFieldFilters([f('min', [], '3'), f('max', [], '8')], fields, values)).toBe(true);
    expect(matchesFieldFilters([f('min', [], '3'), f('max', [], '4')], fields, values)).toBe(false);
    expect(matchesFieldFilters([f('min', [], '9')], new Map(), values)).toBe(true);
  });

  it('sorts select fields by option order and groups multi-values into each group', () => {
    const select = field('single_select', {
      options: [
        { id: 'b', label: 'Plan', color: 'proj-1', archived: false },
        { id: 'a', label: 'Ship', color: 'proj-1', archived: false },
      ],
    } as Partial<Field>);
    expect(fieldSortValue(select, 'b')).toBe(0);
    expect(fieldSortValue(select, 'a')).toBe(1);
    expect(fieldSortValue(select, undefined)).toBeNull();
    expect(fieldGroupKeys(field('multi_select'), ['x', 'y'])).toEqual(['x', 'y']);
    expect(fieldGroupKeys(field('checkbox'), undefined)).toEqual(['none']);
    expect(describeFieldFilter(f('any', ['a', 'none']), select, () => undefined)).toBe(
      'Stage: Ship, No value',
    );
    expect(describeFieldFilter(f('min', [], '3'), field('number', { name: 'Points' }), () => undefined)).toBe(
      'Points ≥ 3',
    );
  });
});
