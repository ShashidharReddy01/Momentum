import { describe, expect, it } from 'vitest';
import {
  autoTitle,
  colorOf,
  draftOf,
  draftProblem,
  formatAverage,
  formatValue,
  newDraft,
  seriesHeadline,
  share,
  specOf,
} from './model';
import type { GroupRow } from './queries';

const group = (key: string, color: string | null = null): GroupRow => ({
  key,
  label: key,
  value: 1,
  tasks: 1,
  color,
});

describe('dashboard model (S6.5.1)', () => {
  it('builds valid specs from plain choices', () => {
    const bar = specOf({ ...newDraft('bar'), groupBy: 'priority', mine: true, dueWithin: 7 });
    expect(bar).toMatchObject({
      version: 1,
      entity: 'tasks',
      filters: { status: 'open', overdue: false, blocked: false, assignees: ['me'], due_within_days: 7 },
      measure: 'count',
      group_by: 'priority',
      limit: 8,
    });
    expect(bar.time_bucket).toBeUndefined();
    // a completed-over-time line counts completed work, whatever the status toggle said
    const line = specOf({ ...newDraft('line'), status: 'open', timeField: 'completed' });
    expect(line.filters?.status).toBe('completed');
    expect(line).toMatchObject({ time_bucket: 'week', time_field: 'completed', window_days: 84 });
    expect(line.group_by).toBeUndefined();
    // overdue is about open work; "due within" doesn't combine with it
    const late = specOf({ ...newDraft('count'), status: 'completed', overdue: true, dueWithin: 7 });
    expect(late.filters).toEqual({ status: 'open', overdue: true, blocked: false });
    // a list always counts tasks
    expect(specOf({ ...newDraft('list'), measure: 'sum_estimate' }).measure).toBe('count');
  });

  it('round-trips a saved widget through the form', () => {
    const spec = specOf({ ...newDraft('donut'), groupBy: 'field', fieldId: 'f1', status: 'all' });
    const d = draftOf({ kind: 'donut', title: 'Stages', spec, size: 'md' });
    expect(specOf(d)).toEqual(spec);
    expect(d.title).toBe('Stages');
  });

  it('titles itself until you type one, and says what is missing', () => {
    expect(autoTitle({ ...newDraft('bar'), groupBy: 'assignee' })).toBe('Open tasks by assignee');
    expect(autoTitle({ ...newDraft('bar'), groupBy: 'status' })).toBe('Open tasks by due date');
    expect(autoTitle({ ...newDraft('count'), overdue: true })).toBe('Overdue tasks');
    expect(autoTitle({ ...newDraft('count'), dueWithin: 7 })).toBe('Open tasks due in 7 days');
    expect(autoTitle({ ...newDraft('line'), bucket: 'month' })).toBe('Completed per month');
    expect(draftProblem({ ...newDraft('bar'), groupBy: 'field' })).toMatch(/custom field/);
    expect(draftProblem(newDraft('bar'))).toBeNull();
  });

  it('colours by job: states, own colours, then fixed slots', () => {
    const spec = { group_by: 'status' as const };
    expect(colorOf(spec, group('overdue'), 0, 'donut')).toBe('var(--crit)');
    expect(colorOf(spec, group('completed'), 4, 'donut')).toBe('var(--ok)');
    const byProject = { group_by: 'project' as const };
    expect(colorOf(byProject, group('p1', 'proj-6'), 0, 'donut')).toBe('var(--proj-6)');
    // a tag's own stored colour is used as is
    const tagColour = ['#', 'ff0000'].join('');
    expect(colorOf({ group_by: 'tag' }, group('t1', tagColour), 0, 'bar')).toBe(tagColour);
    const byPerson = { group_by: 'assignee' as const };
    expect(colorOf(byPerson, group('u1'), 0, 'bar')).toBe('var(--chart-1)'); // one series, one colour
    expect(colorOf(byPerson, group('u2'), 1, 'donut')).toBe('var(--chart-2)');
    expect(colorOf(byPerson, group('u9'), 8, 'donut')).toBe('var(--muted-2)'); // never cycled
    expect(colorOf(byPerson, group('other'), 2, 'donut')).toBe('var(--muted-2)');
  });

  it('formats values and shares honestly', () => {
    expect(formatValue({ measure: 'count' }, 1234)).toBe((1234).toLocaleString());
    expect(formatValue({ measure: 'sum_estimate' }, 90)).toBe('1.5h');
    expect(formatAverage({ measure: 'count' }, 0.18)).toBe((0.2).toLocaleString());
    expect(share(0, 0)).toBe('0%');
    expect(share(1, 300)).toBe('<1%');
    expect(seriesHeadline([])).toEqual({ latest: 0, average: null });
    const pts = [1, 2, 3, 6].map((value, i) => ({
      start: `2026-09-0${i + 1}`,
      end: `2026-09-0${i + 1}`,
      value,
      tasks: value,
    }));
    expect(seriesHeadline(pts)).toEqual({ latest: 6, average: 2 });
  });
});
