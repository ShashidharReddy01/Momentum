import { describe, expect, it } from 'vitest';
import type { Task } from './queries';
import {
  DEFAULT_VIEW,
  dueBucket,
  groupTasks,
  isDefaultView,
  matches,
  sortTasks,
  viewFromParams,
  viewToParams,
} from './view';

// Wednesday 23 Sep 2026 (local)
const TODAY = new Date(2026, 8, 23);
const UUID = '01a0ccaf-8f68-77d2-a888-584ea1e80ea8';

const task = (id: string, over: Partial<Task> = {}): Task => ({
  id,
  number: 1,
  key: 'T-1',
  title: id,
  type: 'task',
  project_id: 'p',
  section_id: 's',
  position: 'a',
  assignee_id: null,
  start_on: null,
  due_on: null,
  due_at: null,
  completed_at: null,
  parent_id: null,
  priority: null,
  version: 1,
  created_at: '2026-09-01T00:00:00Z',
  subtask_count: 0,
  completed_subtask_count: 0,
  ...over,
});

describe('URL params', () => {
  it('round-trips, omits defaults and keeps unrelated params', () => {
    const view = {
      assignees: ['me', UUID],
      due: 'today',
      show_completed: true,
      sort: 'due',
      group: 'assignee',
    } as const;
    const params = viewToParams({ ...view, assignees: [...view.assignees] }, new URLSearchParams('task=abc'));
    expect(params.get('task')).toBe('abc');
    expect(viewFromParams(params)).toEqual(view);
    expect(viewToParams(DEFAULT_VIEW, new URLSearchParams('sort=due&task=1')).toString()).toBe('task=1');
    expect(viewFromParams(new URLSearchParams('task=1'))).toBeNull();
  });

  it('drops invalid values instead of failing', () => {
    const v = viewFromParams(
      new URLSearchParams('sort=evil&group=x&due=later&assignee=<script>&assignee=none&assignee=none'),
    );
    expect(v).toEqual({ ...DEFAULT_VIEW, assignees: ['none'] });
    expect(isDefaultView(DEFAULT_VIEW)).toBe(true);
  });
});

describe('due buckets and filters', () => {
  it.each([
    ['2026-09-20', 'overdue'],
    ['2026-09-23', 'today'],
    ['2026-09-27', 'this_week'], // Sunday
    ['2026-09-28', 'next_week'], // Monday
    ['2026-10-04', 'next_week'],
    ['2026-10-05', 'later'],
    [null, 'no_date'],
  ])('%s → %s', (due, bucket) => {
    expect(dueBucket(due, TODAY)).toBe(bucket);
  });

  it('assignee tokens OR together; me needs a user; due filters use buckets', () => {
    const mine = task('mine', { assignee_id: 'u-me', due_on: '2026-09-23' });
    const ana = task('ana', { assignee_id: 'u-ana', due_on: '2026-09-25' });
    const none = task('none');
    const v = (over: Partial<typeof DEFAULT_VIEW>) => ({ ...DEFAULT_VIEW, ...over });
    expect(
      [mine, ana, none]
        .filter((t) => matches(t, v({ assignees: ['me', 'none'] }), 'u-me', TODAY))
        .map((t) => t.id),
    ).toEqual(['mine', 'none']);
    expect(matches(mine, v({ assignees: ['me'] }), undefined, TODAY)).toBe(false);
    expect(
      [mine, ana, none].filter((t) => matches(t, v({ due: 'this_week' }), 'u-me', TODAY)).map((t) => t.id),
    ).toEqual(['mine', 'ana']);
    expect(
      [mine, ana, none].filter((t) => matches(t, v({ due: 'no_date' }), 'u-me', TODAY)).map((t) => t.id),
    ).toEqual(['none']);
  });
});

describe('sort and group', () => {
  const names: Record<string, string> = { a: 'Ana', r: 'Ravi', m: 'Me Person' };
  const nameOf = (id: string) => names[id];
  const list = [
    task('t3', {
      title: 'Item 10',
      assignee_id: 'r',
      due_on: '2026-09-30',
      created_at: '2026-09-03T00:00:00Z',
    }),
    task('t1', { title: 'item 2', due_on: null, created_at: '2026-09-01T00:00:00Z' }),
    task('t2', { title: 'Beta', assignee_id: 'a', due_on: '2026-09-24', created_at: '2026-09-02T00:00:00Z' }),
    task('t4', { title: 'alpha', assignee_id: 'a', due_on: '2026-09-24', due_at: '2026-09-24T08:00:00Z' }),
  ];
  const ids = (ts: Task[]) => ts.map((t) => t.id);

  it('sorts with nulls last and stable ties', () => {
    expect(ids(sortTasks(list, 'manual', nameOf))).toEqual(['t3', 't1', 't2', 't4']);
    expect(ids(sortTasks(list, 'due', nameOf))).toEqual(['t4', 't2', 't3', 't1']);
    expect(ids(sortTasks(list, 'assignee', nameOf))).toEqual(['t2', 't4', 't3', 't1']);
    expect(ids(sortTasks(list, 'title', nameOf))).toEqual(['t4', 't2', 't1', 't3']); // numeric-aware
    expect(ids(sortTasks(list, 'created', nameOf))[0]).toBe('t1');
  });

  it('groups by assignee (unassigned last, "(you)") and by due bucket (empty omitted)', () => {
    expect(groupTasks(list, 'assignee', nameOf, 'a', TODAY).map((g) => [g.name, ids(g.tasks)])).toEqual([
      ['Ana (you)', ['t2', 't4']],
      ['Ravi', ['t3']],
      ['Unassigned', ['t1']],
    ]);
    expect(groupTasks(list, 'due', nameOf, undefined, TODAY).map((g) => g.name)).toEqual([
      'This week',
      'Next week',
      'No due date',
    ]);
  });
});
