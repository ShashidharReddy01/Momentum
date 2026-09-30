import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';
import { toISODate } from '@/lib/dates';
import { mondayOf } from './grid';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const W1 = mondayOf(toISODate(new Date()));
const plus = (iso: string, days: number) => {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return toISODate(d);
};
const W2 = plus(W1, 7);

const week = (week_start: string, extra: Record<string, unknown> = {}) => ({
  week_start,
  capacity_minutes: 1800,
  override: false,
  planned_minutes: 0,
  task_count: 0,
  unestimated: 0,
  ...extra,
});
const person = (
  user_id: string | null,
  name: string,
  weeks: unknown[],
  extra: Record<string, unknown> = {},
) => ({
  user_id,
  name,
  avatar_url: null,
  weekly_minutes: 1800,
  hours_source: 'setting',
  can_edit: false,
  no_date: 0,
  hidden: 0,
  weeks,
  ...extra,
});
const task = (
  id: string,
  title: string,
  assignee_id: string | null,
  weeks: Record<string, number>,
  extra: Record<string, unknown> = {},
) => ({
  id,
  number: 1,
  title,
  assignee_id,
  start_on: null,
  due_on: plus(W1, 2),
  estimate_minutes: 600,
  project_id: 'p1',
  project_name: 'Website Revamp',
  overdue: false,
  version: 1,
  weeks,
  ...extra,
});

const WORKLOAD = {
  start: W1,
  weeks: [W1, W2],
  default_minutes: 1800,
  default_source: 'setting',
  can_admin: true,
  people: [
    person(
      'u-ana',
      'Ana Souza',
      [week(W1, { planned_minutes: 2400, task_count: 2 }), week(W2, { capacity_minutes: 0, override: true })],
      { hidden: 2 },
    ),
    person(
      'u1',
      'Ravi Kumar',
      [week(W1, { planned_minutes: 600, task_count: 1, unestimated: 1 }), week(W2)],
      {
        can_edit: true,
      },
    ),
  ],
  unassigned: person(
    null,
    'Unassigned',
    [week(W1, { capacity_minutes: 0 }), week(W2, { capacity_minutes: 0 })],
    {
      weekly_minutes: 0,
    },
  ),
  tasks: [
    task('t1', 'Design the homepage', 'u-ana', { [W1]: 1800 }),
    task('t2', 'Legal review', 'u-ana', { [W1]: 600 }),
    task('t3', 'Write copy', 'u1', { [W1]: 0 }, { estimate_minutes: null }),
  ],
};

function boot() {
  const calls: { url: string; body: unknown }[] = [];
  server.use(...authHandlers({ loggedIn: true }).handlers, ...teamHandlers(), ...projectHandlers());
  server.use(
    http.get('*/api/v1/workload', () => HttpResponse.json(WORKLOAD)),
    http.put('*/api/v1/workload/people/:uid/hours', async ({ request, params }) => {
      calls.push({ url: `hours:${params.uid as string}`, body: await request.json() });
      return HttpResponse.json({ data: { hours: 20 }, meta: { activity_id: 'a1' } });
    }),
    http.put('*/api/v1/workload/people/:uid/weeks/:week', async ({ request, params }) => {
      calls.push({
        url: `week:${params.uid as string}:${params.week as string}`,
        body: await request.json(),
      });
      return HttpResponse.json({ data: { hours: 0 }, meta: { activity_id: 'a2' } });
    }),
    http.patch('*/api/v1/tasks/:id', async ({ request, params }) => {
      calls.push({ url: `patch:${params.id as string}`, body: await request.json() });
      return HttpResponse.json({ data: {}, meta: { activity_id: 'a3' } });
    }),
    http.post('*/api/v1/tasks/:id/reschedule', async ({ request, params }) => {
      calls.push({ url: `reschedule:${params.id as string}`, body: await request.json() });
      return HttpResponse.json({
        data: { changes: [], skipped: [], hidden_skipped: 0 },
        meta: { batch_id: 'b1' },
      });
    }),
  );
  window.history.replaceState(null, '', '/workload');
  render(<MomentumApp />);
  return { calls, user: userEvent.setup() };
}

const cell = (name: RegExp) => screen.getByRole('button', { name });

describe('Workload (S6.4.1)', () => {
  it('shows each person’s weeks against their hours, tinted by how full they are', async () => {
    boot();
    await screen.findByRole('grid', { name: 'Workload' });
    const over = cell(/^Ana Souza, week of .*40h planned of 30h 2 tasks over capacity/);
    expect(over).toHaveTextContent('40h / 30h');
    expect(over.className).toContain('bg-crit-tint');
    expect(cell(/^Ana Souza, week of .*of 0h/)).toHaveTextContent('Away');
    expect(cell(/^Ravi Kumar, week of .*1 without an estimate/)).toHaveTextContent('+1 unestimated');
    // hidden work: counted, never named
    expect(screen.getByText('2 elsewhere')).toBeInTheDocument();
    expect(screen.getByText(/2 open tasks elsewhere are counted, not shown/)).toBeInTheDocument();
    // a count view for teams that don't estimate
    await userEvent.setup().click(screen.getByRole('button', { name: 'Tasks' }));
    expect(over).toHaveTextContent('2 tasks');
  });

  it('opens a week to list its tasks and moves one a week later (dependency-aware)', async () => {
    const { calls, user } = boot();
    await screen.findByRole('grid', { name: 'Workload' });
    await user.click(cell(/^Ana Souza, week of .*40h planned/));
    const list = await screen.findByRole('list', { name: /Ana Souza's tasks/ });
    expect(within(list).getByText('Design the homepage')).toBeInTheDocument();
    await user.click(within(list).getByRole('button', { name: 'Move Legal review' }));
    await user.click(await screen.findByRole('menuitem', { name: 'A week later' }));
    await waitFor(() => expect(calls.find((c) => c.url === 'reschedule:t2')).toBeTruthy());
    expect(calls.find((c) => c.url === 'reschedule:t2')!.body).toEqual({
      start_on: null,
      due_on: plus(W1, 9),
      cascade: true,
    });
  });

  it('gives a task to someone else from the menu', async () => {
    const { calls, user } = boot();
    await screen.findByRole('grid', { name: 'Workload' });
    await user.click(cell(/^Ana Souza, week of .*40h planned/));
    const list = await screen.findByRole('list', { name: /Ana Souza's tasks/ });
    await user.click(within(list).getByRole('button', { name: 'Move Design the homepage' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Ravi Kumar' }));
    await waitFor(() => expect(calls.find((c) => c.url === 'patch:t1')!.body).toEqual({ assignee_id: 'u1' }));
  });

  it('lets people set their own hours and take a week off', async () => {
    const { calls, user } = boot();
    await screen.findByRole('grid', { name: 'Workload' });
    expect(screen.queryByRole('button', { name: /Ana Souza's usual hours/ })).toBeNull(); // not hers to edit
    await user.click(screen.getByRole('button', { name: /Ravi Kumar's usual hours: 30h\/wk/ }));
    const form = await screen.findByRole('form', { name: 'Usual weekly hours' });
    const input = within(form).getByLabelText('Usual hours a week');
    await user.clear(input);
    await user.type(input, '20');
    await user.click(within(form).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.find((c) => c.url === 'hours:u1')!.body).toEqual({ hours: 20 }));

    await user.click(cell(/^Ravi Kumar, week of .*10h planned/));
    const weekForm = await screen.findByRole('form', { name: "This week's hours" });
    await user.click(within(weekForm).getByRole('button', { name: 'Away all week' }));
    await waitFor(() => expect(calls.find((c) => c.url === `week:u1:${W1}`)!.body).toEqual({ hours: 0 }));
  });
});
