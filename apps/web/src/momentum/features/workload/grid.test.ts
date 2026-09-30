import { describe, expect, it } from 'vitest';
import { mondayOf, shiftWeeks, toneOf, weeksBetween } from './grid';

describe('workload grid (S6.4.1)', () => {
  it('tones a week by how full it is', () => {
    expect(toneOf(0, 1800)).toBe('idle');
    expect(toneOf(1200, 1800)).toBe('ok');
    expect(toneOf(1700, 1800)).toBe('warn');
    expect(toneOf(1900, 1800)).toBe('crit');
    expect(toneOf(0, 0)).toBe('away');
    expect(toneOf(60, 0)).toBe('crit');
  });
  it('moves dates by whole weeks', () => {
    expect(mondayOf('2030-01-11')).toBe('2030-01-07');
    expect(mondayOf('2030-01-07')).toBe('2030-01-07');
    expect(mondayOf('2030-01-13')).toBe('2030-01-07'); // Sunday belongs to the week before
    expect(shiftWeeks({ start_on: '2030-01-07', due_on: '2030-01-11' }, 1)).toEqual({
      start_on: '2030-01-14',
      due_on: '2030-01-18',
    });
    expect(shiftWeeks({ due_on: '2030-01-11' }, -1)).toEqual({ start_on: null, due_on: '2030-01-04' });
    expect(weeksBetween('2030-01-07', '2030-01-21')).toBe(2);
  });
});
