import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { addDays, toISODate } from '@/lib/dates';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
// jsdom has no layout: give the scroll container a viewport so the virtualizer mounts rows.
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(800);
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(1200);
});
afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
  window.localStorage.clear();
});
afterAll(() => server.close());

const iso = (days: number) => toISODate(addDays(new Date(), days));

function task(
  n: number,
  title: string,
  section: string,
  start: number | null,
  due: number | null,
  extra = {},
) {
  return {
    id: `t${n}`,
    number: n,
    key: `T-${n}`,
    title,
    type: 'task',
    approval_state: null,
    project_id: 'seed-1',
    section_id: section,
    position: String(100000 + n),
    assignee_id: null,
    start_on: start === null ? null : iso(start),
    due_on: due === null ? null : iso(due),
    due_at: null,
    completed_at: null,
    parent_id: null,
    priority: null,
    version: 1,
    created_at: new Date().toISOString(),
    subtask_count: 0,
    completed_subtask_count: 0,
    ...extra,
  };
}

const patches: { id: string; body: Record<string, unknown> }[] = [];

async function boot(
  tasks: ReturnType<typeof task>[],
  edges: { task_id: string; depends_on_id: string }[],
  role: 'admin' | 'viewer' = 'admin',
) {
  patches.length = 0;
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: role }]),
    ...sectionHandlers('', { 'seed-1': ['Design', 'Build'] }),
    ...taskHandlers('', {}),
  );
  server.use(
    http.get('*/api/v1/projects/:pid/tasks', ({ request }) =>
      HttpResponse.json({
        data: new URL(request.url).searchParams.get('completed') === 'true' ? [] : tasks,
      }),
    ),
    http.get('*/api/v1/projects/:pid/dependencies', () => HttpResponse.json({ data: edges })),
    http.patch('*/api/v1/tasks/:id', async ({ params, request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      patches.push({ id: String(params.id), body });
      const t = tasks.find((x) => x.id === params.id)!;
      return HttpResponse.json({
        data: { ...t, ...body, version: t.version + 1 },
        meta: { activity_id: 'a1' },
      });
    }),
  );
  window.history.replaceState(null, '', '/projects/seed-1/timeline');
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Timeline view', () => {
  it('draws scheduled tasks as bars by section, a milestone, and undated tasks in the tray', async () => {
    await boot(
      [
        task(1, 'Wireframes', 'sec-1', -2, 3),
        task(2, 'Launch', 'sec-2', null, 20, { type: 'milestone' }),
        task(3, 'Someday idea', 'sec-1', null, null),
      ],
      [],
    );
    const chart = await screen.findByRole('region', { name: 'Timeline chart' });
    expect(within(chart).getByRole('button', { name: 'Design' })).toHaveAttribute('aria-expanded', 'true');
    expect(within(chart).getByRole('button', { name: /^T-1 Wireframes, .* 6 days$/ })).toBeInTheDocument();
    expect(within(chart).getByRole('button', { name: /^T-2 Launch, / })).toHaveClass('rotate-45');
    const tray = screen.getByRole('complementary', { name: 'Unscheduled' });
    expect(within(tray).getByRole('listitem', { name: 'Someday idea' })).toBeInTheDocument();
    expect(screen.getByText('2 scheduled · 1 unscheduled')).toBeInTheDocument();
  });

  it('highlights the critical path and counts conflicts, with arrows for each dependency', async () => {
    const user = await boot(
      [
        task(1, 'Design', 'sec-1', 0, 4),
        task(2, 'Build', 'sec-2', 5, 14),
        task(3, 'Docs', 'sec-2', 2, 3), // starts before Design is due: a conflict
      ],
      [
        { task_id: 't2', depends_on_id: 't1' },
        { task_id: 't3', depends_on_id: 't1' },
      ],
    );
    const pathToggle = await screen.findByRole('button', { name: /Critical path · 2 tasks, 15 days/ });
    expect(pathToggle).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '1 conflict' })).toBeInTheDocument();
    const chart = screen.getByRole('region', { name: 'Timeline chart' });
    expect(
      within(chart).getByRole('button', { name: /^T-2 Build, .*on the critical path$/ }),
    ).toBeInTheDocument();
    expect(
      within(chart).getByRole('button', { name: /^T-3 Docs, .*starts before its blocker is due$/ }),
    ).toBeInTheDocument();
    const kinds = [...document.querySelectorAll('path[data-edge]')].map((p) => p.getAttribute('data-kind'));
    expect(kinds.sort()).toEqual(['conflict', 'critical']);

    await user.click(pathToggle);
    expect(pathToggle).toHaveAttribute('aria-pressed', 'false');
    await waitFor(() =>
      expect(within(chart).getByRole('button', { name: /^T-2 Build, .* days$/ })).toBeInTheDocument(),
    );
  });

  it('collapses a section and switches zoom', async () => {
    const user = await boot([task(1, 'Wireframes', 'sec-1', 0, 3), task(2, 'API', 'sec-2', 4, 9)], []);
    const chart = await screen.findByRole('region', { name: 'Timeline chart' });
    await user.click(within(chart).getByRole('button', { name: 'Design' }));
    expect(within(chart).queryByRole('button', { name: /^T-1 Wireframes/ })).not.toBeInTheDocument();
    expect(within(chart).getByRole('button', { name: /^T-2 API/ })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Week' }));
    expect(screen.getByRole('button', { name: 'Week' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(chart).getAllByText('Today').length).toBeGreaterThan(0);
  });

  it('shows a helpful empty state for a project with no tasks', async () => {
    await boot([], []);
    expect(await screen.findByText('No tasks yet')).toBeInTheDocument();
  });
});

describe('Timeline editing', () => {
  const bar = (name: RegExp) =>
    within(screen.getByRole('region', { name: 'Timeline chart' })).getByRole('button', { name });

  it('drags a bar to move both dates by whole days (month zoom: 16 px a day)', async () => {
    await boot([task(1, 'Wireframes', 'sec-1', 0, 3)], []);
    await screen.findByRole('region', { name: 'Timeline chart' });
    const b = bar(/^T-1 Wireframes/);
    fireEvent.pointerDown(b, { button: 0, clientX: 500 });
    fireEvent.pointerMove(window, { clientX: 500 + 16 * 3 });
    expect(await screen.findByRole('status')).toHaveTextContent('(+3 days)');
    fireEvent.pointerUp(window, { clientX: 500 + 16 * 3 });
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ id: 't1', body: { start_on: iso(3), due_on: iso(6) } });
  });

  it('drags the end handle to change only the due date', async () => {
    await boot([task(1, 'Wireframes', 'sec-1', 0, 3)], []);
    await screen.findByRole('region', { name: 'Timeline chart' });
    const handle = bar(/^T-1 Wireframes/).querySelector('[data-handle="end"]')!;
    fireEvent.pointerDown(handle, { button: 0, clientX: 500 });
    fireEvent.pointerMove(window, { clientX: 500 + 16 * 2 });
    fireEvent.pointerUp(window, { clientX: 500 + 16 * 2 });
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]!.body).toEqual({ due_on: iso(5) });
  });

  it('a press without movement opens the task instead of moving it', async () => {
    await boot([task(1, 'Wireframes', 'sec-1', 0, 3)], []);
    await screen.findByRole('region', { name: 'Timeline chart' });
    const b = bar(/^T-1 Wireframes/);
    fireEvent.pointerDown(b, { button: 0, clientX: 500 });
    fireEvent.pointerUp(window, { clientX: 501 });
    fireEvent.click(b);
    await waitFor(() => expect(window.location.search).toContain('task=t1'));
    expect(patches).toHaveLength(0);
  });

  it('nudges the focused task with the arrow keys (Shift: a week)', async () => {
    const user = await boot([task(1, 'Wireframes', 'sec-1', 0, 3), task(2, 'API', 'sec-2', 4, 9)], []);
    await screen.findByRole('region', { name: 'Timeline chart' });
    bar(/^T-1 Wireframes/).focus();
    await user.keyboard('{ArrowRight}');
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]!.body).toEqual({ start_on: iso(1), due_on: iso(4) });
    await user.keyboard('j');
    await waitFor(() => expect(bar(/^T-2 API/)).toHaveFocus());
    await user.keyboard('{Shift>}{ArrowLeft}{/Shift}');
    await waitFor(() => expect(patches).toHaveLength(2));
    expect(patches[1]).toEqual({ id: 't2', body: { start_on: iso(-3), due_on: iso(2) } });
  });

  it('schedules an unscheduled task by dropping it on a day', async () => {
    await boot([task(1, 'Wireframes', 'sec-1', 0, 3), task(2, 'Someday', 'sec-1', null, null)], []);
    const chart = await screen.findByRole('region', { name: 'Timeline chart' });
    vi.spyOn(chart, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: 1200,
      bottom: 800,
      width: 1200,
      height: 800,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    const item = within(screen.getByRole('complementary', { name: 'Unscheduled' })).getByRole('button', {
      name: 'Someday',
    });
    fireEvent.pointerDown(item, { button: 0, clientX: 1300, clientY: 100 });
    // 280 px task column, then 16 px a day from the range start
    fireEvent.pointerMove(window, { clientX: 280 + 16 * 10 + 4, clientY: 100 });
    expect(await screen.findByText(/^Schedule for /)).toBeInTheDocument();
    fireEvent.pointerUp(window, { clientX: 280 + 16 * 10 + 4, clientY: 100 });
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]!.id).toBe('t2');
    expect(Object.keys(patches[0]!.body)).toEqual(['due_on']);
  });

  it('is read-only for a viewer: no handles, no drag, no nudge', async () => {
    const user = await boot([task(1, 'Wireframes', 'sec-1', 0, 3)], [], 'viewer');
    await screen.findByRole('region', { name: 'Timeline chart' });
    const b = bar(/^T-1 Wireframes/);
    expect(b.querySelector('[data-handle]')).toBeNull();
    fireEvent.pointerDown(b, { button: 0, clientX: 500 });
    fireEvent.pointerMove(window, { clientX: 600 });
    fireEvent.pointerUp(window, { clientX: 600 });
    b.focus();
    await user.keyboard('{ArrowRight}');
    expect(patches).toHaveLength(0);
  });
});
