import { describe, expect, it } from 'vitest';
import { dueTone, formatDay, formatDue, nextWeek, parseNaturalDate, toISODate } from './dates';

// Frozen "now": Wednesday 23 Sep 2026, 10:00 local time. Expectations use local constructors,
// so the table holds in any test-runner timezone.
const NOW = new Date(2026, 8, 23, 10, 0);

describe('parseNaturalDate', () => {
  it.each([
    ['today', '2026-09-23', null],
    ['tomorrow', '2026-09-24', null],
    ['fri', '2026-09-25', null],
    ['next fri', '2026-10-02', null],
    ['in 3 days', '2026-09-26', null],
    ['sept 30', '2026-09-30', null],
    ['jan 5', '2027-01-05', null], // no year → next occurrence
    ['tomorrow 5pm', '2026-09-24', new Date(2026, 8, 24, 17, 0)],
    ['oct 1 at 9:30am', '2026-10-01', new Date(2026, 9, 1, 9, 30)],
  ])('%s → %s', (text, date, at) => {
    expect(parseNaturalDate(text, NOW)).toEqual({ date, at: at ? at.toISOString() : null });
  });

  it('returns null for text that is not a date', () => {
    expect(parseNaturalDate('asdf', NOW)).toBeNull();
    expect(parseNaturalDate('   ', NOW)).toBeNull();
  });
});

describe('due formatting', () => {
  it('labels relative days and dates', () => {
    expect(formatDay('2026-09-23', NOW)).toBe('Today');
    expect(formatDay('2026-09-24', NOW)).toBe('Tomorrow');
    expect(formatDay('2026-09-22', NOW)).toBe('Yesterday');
    expect(formatDay('2026-09-26', NOW)).toMatch(/Saturday/);
    expect(formatDay('2026-10-05', NOW)).toMatch(/Oct/);
    expect(formatDay('2027-01-05', NOW)).toMatch(/2027/);
    expect(formatDue('2026-09-24', null, '2026-09-22', NOW)).toBe('Yesterday – Tomorrow');
  });

  it('tones: overdue, today, done', () => {
    expect(dueTone('2026-09-22', null, false, NOW)).toBe('overdue');
    expect(dueTone('2026-09-23', null, false, NOW)).toBe('today');
    expect(dueTone('2026-09-23', new Date(2026, 8, 23, 9).toISOString(), false, NOW)).toBe('overdue');
    expect(dueTone('2026-09-22', null, true, NOW)).toBe('done');
    expect(dueTone('2026-09-30', null, false, NOW)).toBe('later');
  });

  it('next week is next Monday', () => {
    expect(toISODate(nextWeek(NOW))).toBe('2026-09-28');
    expect(toISODate(nextWeek(new Date(2026, 8, 28)))).toBe('2026-10-05');
  });
});
