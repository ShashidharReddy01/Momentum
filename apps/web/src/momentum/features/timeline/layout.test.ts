import { describe, expect, it } from 'vitest';
import { fromISODate } from '@/lib/dates';
import {
  arrowPath,
  conflictsOf,
  criticalPath,
  rangeOf,
  rowsOf,
  spanOf,
  ticksOf,
  type DatedTask,
} from './layout';

const t = (
  id: string,
  start: string | null,
  due: string | null,
  extra: Partial<DatedTask> = {},
): DatedTask => ({
  id,
  type: 'task',
  start_on: start,
  due_on: due,
  completed_at: null,
  section_id: 's1',
  ...extra,
});

describe('spanOf', () => {
  it('draws start → due, a one-day bar for a single date, and nothing without dates', () => {
    expect(spanOf(t('a', '2026-10-01', '2026-10-05'))).toEqual({ start: '2026-10-01', end: '2026-10-05' });
    expect(spanOf(t('a', null, '2026-10-05'))).toEqual({ start: '2026-10-05', end: '2026-10-05' });
    expect(spanOf(t('a', '2026-10-01', null))).toEqual({ start: '2026-10-01', end: '2026-10-01' });
    expect(spanOf(t('a', null, null))).toBeNull();
  });

  it('puts a milestone on its due date and never draws a bar backwards', () => {
    expect(spanOf(t('m', '2026-10-01', '2026-10-09', { type: 'milestone' }))).toEqual({
      start: '2026-10-09',
      end: '2026-10-09',
    });
    expect(spanOf(t('a', '2026-10-09', '2026-10-01'))).toEqual({ start: '2026-10-01', end: '2026-10-01' });
  });
});

describe('rangeOf and ticks', () => {
  it('starts on a Monday, covers every bar and today, with room either side', () => {
    const today = fromISODate('2026-09-30');
    const r = rangeOf([{ start: '2026-06-10', end: '2027-02-01' }], today);
    expect(r.start.getDay()).toBe(1);
    expect(r.start <= fromISODate('2026-06-10')).toBe(true);
    const end = new Date(r.start);
    end.setDate(end.getDate() + r.days);
    expect(end > fromISODate('2027-02-01')).toBe(true);
  });

  it('labels months, weekends and today at week zoom, quarters when zoomed out', () => {
    const today = fromISODate('2026-09-30');
    const start = fromISODate('2026-09-28'); // a Monday
    const week = ticksOf(start, 14, 'week', today);
    expect(week.minor).toHaveLength(14);
    expect(week.minor.filter((m) => m.weekend)).toHaveLength(4);
    expect(week.minor.find((m) => m.today)?.label).toBe('30');
    expect(week.major.map((m) => m.x)).toEqual([0, 3 * 40]); // Sep, then Oct from the 1st
    const quarter = ticksOf(start, 120, 'quarter', today);
    expect(quarter.major.map((m) => m.label)).toEqual(['Q3 2026', 'Q4 2026', 'Q1 2027']);
  });
});

describe('rowsOf', () => {
  it('groups by section in order, sends undated tasks to the tray, and hides collapsed sections', () => {
    const sections = [
      { id: 's1', name: 'Design' },
      { id: 's2', name: 'Build' },
    ];
    const tasks = [
      t('a', '2026-10-01', '2026-10-02'),
      t('b', null, null),
      t('c', null, '2026-10-09', { section_id: 's2' }),
    ];
    const { rows, unscheduled } = rowsOf(sections, tasks, new Set(['s2']));
    expect(unscheduled.map((x) => x.id)).toEqual(['b']);
    expect(rows.map((r) => (r.kind === 'section' ? `#${r.name}:${r.count}` : r.task.id))).toEqual([
      '#Design:1',
      'a',
      '#Build:1',
    ]);
  });
});

describe('criticalPath', () => {
  it('follows the longest chain of dependent open work', () => {
    const tasks = [
      t('design', '2026-10-01', '2026-10-05'), // 5 days
      t('copy', '2026-10-01', '2026-10-02'), // 2 days
      t('build', '2026-10-06', '2026-10-15'), // 10 days
      t('qa', '2026-10-16', '2026-10-18'), // 3 days
      t('alone', '2026-10-01', '2026-12-31'), // long but linked to nothing
    ];
    const edges = [
      { task_id: 'build', depends_on_id: 'design' },
      { task_id: 'build', depends_on_id: 'copy' },
      { task_id: 'qa', depends_on_id: 'build' },
    ];
    expect(criticalPath(tasks, edges)).toEqual(['design', 'build', 'qa']);
  });

  it('ignores completed work and returns nothing without a chain', () => {
    const tasks = [
      t('a', '2026-10-01', '2026-10-05', { completed_at: '2026-10-05T10:00:00Z' }),
      t('b', '2026-10-06', '2026-10-08'),
    ];
    expect(criticalPath(tasks, [{ task_id: 'b', depends_on_id: 'a' }])).toEqual([]);
    expect(criticalPath(tasks, [])).toEqual([]);
  });

  it('does not loop on a cycle', () => {
    const tasks = [t('a', '2026-10-01', '2026-10-02'), t('b', '2026-10-03', '2026-10-04')];
    const edges = [
      { task_id: 'a', depends_on_id: 'b' },
      { task_id: 'b', depends_on_id: 'a' },
    ];
    expect(criticalPath(tasks, edges)).toEqual([]);
  });
});

describe('conflictsOf', () => {
  it('flags a dependent drawn to start before its blocker is due, allowing same-day hand-offs', () => {
    const tasks = [
      t('blocker', '2026-10-01', '2026-10-05'),
      t('early', '2026-10-03', '2026-10-08'),
      t('sameday', '2026-10-05', '2026-10-08'),
      t('after', '2026-10-06', '2026-10-08'),
    ];
    const edges = ['early', 'sameday', 'after'].map((id) => ({ task_id: id, depends_on_id: 'blocker' }));
    expect([...conflictsOf(tasks, edges)]).toEqual(['blocker>early']);
  });
});

describe('arrowPath', () => {
  it('goes straight across when there is room and doubles back when there is not', () => {
    expect(arrowPath(100, 18, 200, 54)).toBe('M100,18 H108 V54 H200');
    expect(arrowPath(100, 18, 90, 54)).toBe('M100,18 H108 V36 H82 V54 H90');
  });
});
