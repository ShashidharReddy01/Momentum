import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const now = new Date().toISOString();
const widget = (id: string, kind: string, title: string, query_spec: object, size = 'md') => ({
  id,
  kind,
  title,
  query_spec,
  viz: { size },
  version: 1,
});
const DETAIL = {
  id: 'd1',
  name: 'Delivery',
  description: null,
  scope: 'workspace',
  project_id: null,
  owner_id: 'u1',
  version: 1,
  can_edit: true,
  widget_count: 3,
  created_at: now,
  updated_at: now,
  widgets: [
    widget('w-count', 'count', 'Overdue', { filters: { overdue: true } }, 'sm'),
    {
      ...widget('w-bar', 'bar', 'Open tasks by assignee', { group_by: 'assignee' }),
      created_from_prompt: 'who has what?',
    },
    widget('w-list', 'list', 'Overdue work', { filters: { overdue: true }, limit: 10 }, 'lg'),
  ],
};
const task = (n: number, title: string) => ({
  id: `t${n}`,
  key: `T-${n}`,
  title,
  assignee_id: 'u1',
  assignee_name: 'Ravi Kumar',
  due_on: '2026-01-02',
  completed_at: null,
  estimate_minutes: null,
  project_id: 'p1',
  project_name: 'Website Revamp',
  project_color: 'proj-6',
});
const base = {
  measure: 'count',
  unestimated: 0,
  groups: [],
  series: [],
  tasks: [],
  more: 0,
  computed_at: now,
};
const DATA: Record<string, object> = {
  'w-count': { ...base, kind: 'count', description: 'Overdue tasks', value: 3, total: 3, tasks_total: 3 },
  'w-bar': {
    ...base,
    kind: 'bar',
    description: 'Open tasks · by assignee',
    total: 7,
    tasks_total: 7,
    groups: [
      { key: 'u1', label: 'Ravi Kumar', value: 5, tasks: 5, color: null },
      { key: 'none', label: 'Unassigned', value: 2, tasks: 2, color: null },
    ],
  },
  'w-list': {
    ...base,
    kind: 'list',
    description: 'Overdue tasks',
    total: 3,
    tasks_total: 3,
    tasks: [task(12, 'Fix the pricing page')],
    more: 2,
  },
};

function boot(detail: object = DETAIL) {
  const drills: Record<string, unknown>[] = [];
  const queries: Record<string, unknown>[] = [];
  const added: Record<string, unknown>[] = [];
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    http.get('*/api/v1/dashboards/:id', () => HttpResponse.json(detail)),
    http.get('*/api/v1/dashboards/widgets/:wid/data', ({ params }) =>
      HttpResponse.json(DATA[params.wid as string]),
    ),
    http.post('*/api/v1/dashboards/drill', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      drills.push(body);
      return HttpResponse.json({
        label: 'Ravi Kumar',
        total: 2,
        tasks: [task(7, 'Write hero copy'), task(9, 'Audit')],
      });
    }),
    http.post('*/api/v1/dashboards/query', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      queries.push(body);
      return HttpResponse.json({ ...DATA['w-bar'], kind: body.kind });
    }),
    http.post('*/api/v1/ai/dashboards/query', async ({ request }) => {
      const body = (await request.json()) as { text: string };
      if (body.text.includes('revenue'))
        return HttpResponse.json({ question: 'I can chart tasks, not revenue. Open tasks by project?' });
      return HttpResponse.json({
        kind: 'bar',
        title: 'Open tasks by assignee',
        query_spec: { group_by: 'assignee', filters: { status: 'open', overdue: false, blocked: false } },
        named: { people: [] },
        result: DATA['w-bar'],
      });
    }),
    http.post('*/api/v1/dashboards/:id/widgets', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      added.push(body);
      return HttpResponse.json(
        {
          data: { id: 'w-new', version: 1, ...body },
          meta: { activity_id: '01a0ccaf-0000-7000-8000-00000000e001', batch_id: null, version: 1 },
        },
        { status: 201 },
      );
    }),
  );
  window.history.replaceState(null, '', '/dashboards/d1');
  render(<MomentumApp />);
  return { drills, queries, added, user: userEvent.setup() };
}

describe('Dashboards (S6.5.1)', () => {
  it('shows each widget with what it counts, and a number opens the tasks behind it', async () => {
    const { drills, user } = boot();
    const tile = await screen.findByRole('region', { name: 'Overdue' });
    const value = await within(tile).findByRole('button', { name: /3/ });
    expect(value).toHaveClass('flex');
    expect(within(tile).getByText('need attention')).toBeInTheDocument();
    expect(await screen.findByText('Open tasks · by assignee')).toBeInTheDocument();
    expect(screen.getByText(/count top-level tasks in projects you can see/)).toBeInTheDocument();

    await user.click(value);
    const panel = await screen.findByRole('complementary', { name: 'Tasks behind this number' });
    expect(await within(panel).findByText('Write hero copy')).toBeInTheDocument();
    expect(drills[0]).toMatchObject({ query_spec: { filters: { overdue: true } }, key: null });
  });

  it('every chart has a table twin whose rows open their tasks', async () => {
    const { drills, user } = boot();
    const card = await screen.findByRole('region', { name: 'Open tasks by assignee' });
    await user.click(await within(card).findByRole('button', { name: 'Show as table' }));
    const table = within(card).getByRole('table');
    expect(table).toHaveTextContent('Ravi Kumar');
    expect(table).toHaveTextContent('71%');
    await user.click(within(table).getByRole('button', { name: 'Unassigned' }));
    await waitFor(() =>
      expect(drills.at(-1)).toMatchObject({ key: 'none', query_spec: { group_by: 'assignee' } }),
    );
  });

  it('lists overdue work with how late it is', async () => {
    boot();
    const card = await screen.findByRole('region', { name: 'Overdue work' });
    expect(await within(card).findByText('Fix the pricing page')).toBeInTheDocument();
    expect(within(card).getByText(/days late/)).toHaveClass('text-crit');
    expect(within(card).getByRole('button', { name: 'Show all 3' })).toBeInTheDocument();
  });

  it('adds a chart from plain choices with a live preview', async () => {
    const { queries, added, user } = boot();
    await user.click(await screen.findByRole('button', { name: 'Add chart' }));
    const dialog = await screen.findByRole('dialog', { name: 'Add a chart' });
    await user.click(within(dialog).getByRole('button', { name: /Donut/ }));
    await user.selectOptions(within(dialog).getByLabelText('Group by'), 'priority');
    await waitFor(() =>
      expect(queries.at(-1)).toMatchObject({ kind: 'donut', query_spec: { group_by: 'priority' } }),
    );
    expect(within(dialog).getByLabelText('Title')).toHaveValue('Open tasks by priority');
    await user.click(within(dialog).getByRole('button', { name: 'Add chart' }));
    await waitFor(() => expect(added).toHaveLength(1));
    expect(added[0]).toMatchObject({
      kind: 'donut',
      title: 'Open tasks by priority',
      query_spec: { group_by: 'priority', filters: { status: 'open' } },
      viz: { size: 'md' },
    });
  });

  it('is read-only for someone who can view but not edit', async () => {
    boot({ ...DETAIL, can_edit: false });
    await screen.findByRole('region', { name: 'Overdue' });
    expect(screen.queryByRole('button', { name: 'Add chart' })).toBeNull();
    expect(screen.queryByRole('button', { name: /options$/ })).toBeNull();
  });
});

describe('Project Dashboard tab (S6.5.1)', () => {
  it('shows the starter layout live before anyone customises it', async () => {
    const queries: Record<string, unknown>[] = [];
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers('', undefined, [{ name: 'Website Revamp' }]),
      ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
      ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
      http.get('*/api/v1/dashboards/project/:pid', () =>
        HttpResponse.json({
          dashboard: null,
          can_edit: true,
          starter: [
            { kind: 'count', title: 'Open tasks', query_spec: {}, viz: { size: 'sm' } },
            {
              kind: 'bar',
              title: 'Open tasks by section',
              query_spec: { group_by: 'section' },
              viz: { size: 'md' },
            },
          ],
        }),
      ),
      http.post('*/api/v1/dashboards/query', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        queries.push(body);
        return HttpResponse.json(body.kind === 'count' ? DATA['w-count'] : DATA['w-bar']);
      }),
    );
    window.history.replaceState(null, '', '/projects/seed-1/dashboard');
    render(<MomentumApp />);
    expect(await screen.findByText(/The starter dashboard, with live numbers/)).toBeInTheDocument();
    expect(await screen.findByRole('region', { name: 'Open tasks by section' })).toBeInTheDocument();
    await waitFor(() => expect(queries.length).toBeGreaterThanOrEqual(2));
    expect(queries.every((q) => q.project_id === 'seed-1')).toBe(true);
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page');
  });
});

describe('Ask for a chart (S6.5.2)', () => {
  it('turns a question into a live chart and adds it with the question remembered', async () => {
    const { added, user } = boot();
    await user.click(await screen.findByRole('button', { name: 'Ask for a chart' }));
    const dialog = await screen.findByRole('dialog', { name: 'Ask for a chart' });
    await user.click(within(dialog).getByRole('button', { name: 'Open tasks by assignee' }));
    const made = await within(dialog).findByRole('region', { name: 'Mo made this chart (AI)' });
    expect(made).toHaveTextContent('Open tasks · by assignee');
    expect(within(dialog).getByRole('region', { name: 'Open tasks by assignee' })).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Add to dashboard' }));
    await waitFor(() => expect(added).toHaveLength(1));
    expect(added[0]).toMatchObject({
      kind: 'bar',
      title: 'Open tasks by assignee',
      created_from_prompt: 'Open tasks by assignee',
      query_spec: { group_by: 'assignee' },
    });
  });

  it('asks back instead of guessing', async () => {
    const { added, user } = boot();
    await user.click(await screen.findByRole('button', { name: 'Ask for a chart' }));
    const dialog = await screen.findByRole('dialog', { name: 'Ask for a chart' });
    await user.type(within(dialog).getByLabelText('What do you want to see?'), 'revenue by quarter');
    await user.click(within(dialog).getByRole('button', { name: /Ask$/ }));
    expect(await within(dialog).findByText(/not revenue/)).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Add to dashboard' })).toBeNull();
    expect(added).toHaveLength(0);
  });

  it('"Adjust first" keeps the filters the form has no control for, as removable chips', async () => {
    const { added, user } = boot();
    const previews: { query_spec: { filters?: Record<string, unknown> } }[] = [];
    server.use(
      http.post('*/api/v1/ai/dashboards/query', () =>
        HttpResponse.json({
          kind: 'bar',
          title: 'Overdue work by assignee',
          query_spec: {
            group_by: 'assignee',
            filters: {
              status: 'open',
              overdue: true,
              blocked: false,
              project_ids: ['p1'],
              priorities: ['high'],
            },
          },
          named: { projects: ['Website Revamp'] },
          result: DATA['w-bar'],
        }),
      ),
      http.post('*/api/v1/dashboards/query', async ({ request }) => {
        const body = (await request.json()) as {
          kind: string;
          query_spec: { filters?: Record<string, unknown> };
        };
        previews.push(body);
        const f = body.query_spec.filters ?? {};
        return HttpResponse.json({
          ...DATA['w-bar'],
          kind: body.kind,
          filter_names: [
            ...((f.project_ids as string[] | undefined) ?? []).map((key) => ({
              filter: 'project_ids',
              key,
              label: 'Website Revamp',
            })),
            ...((f.priorities as string[] | undefined) ?? []).map((key) => ({
              filter: 'priorities',
              key,
              label: 'High',
            })),
          ],
        });
      }),
    );
    await user.click(await screen.findByRole('button', { name: 'Ask for a chart' }));
    const asking = await screen.findByRole('dialog', { name: 'Ask for a chart' });
    await user.type(within(asking).getByLabelText('What do you want to see?'), 'overdue in website revamp');
    await user.click(within(asking).getByRole('button', { name: /Ask$/ }));
    await user.click(await within(asking).findByRole('button', { name: 'Adjust first' }));

    const editor = await screen.findByRole('dialog', { name: 'Add a chart' });
    expect(await within(editor).findByText('Project: Website Revamp')).toBeInTheDocument();
    expect(within(editor).getByText('Priority: High')).toBeInTheDocument();
    await user.click(within(editor).getByRole('button', { name: 'Remove Priority: High' }));
    await waitFor(() => expect(previews.at(-1)?.query_spec.filters).not.toHaveProperty('priorities'));
    await user.click(within(editor).getByRole('button', { name: 'Add chart' }));
    await waitFor(() => expect(added).toHaveLength(1));
    expect(added[0]).toMatchObject({
      query_spec: { group_by: 'assignee', filters: { overdue: true, project_ids: ['p1'] } },
    });
    expect((added[0]!.query_spec as { filters: object }).filters).not.toHaveProperty('priorities');
  });

  it('marks a chart Mo drafted with the amber sparkle and its question', async () => {
    boot();
    const card = await screen.findByRole('region', { name: 'Open tasks by assignee' });
    expect(within(card).getByRole('img', { name: 'Drafted by Mo from: who has what?' })).toHaveClass(
      'text-amber-ink',
    );
  });
});
