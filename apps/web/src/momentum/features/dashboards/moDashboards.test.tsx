import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const now = new Date().toISOString();
const base = {
  measure: 'count',
  unestimated: 0,
  groups: [],
  series: [],
  tasks: [],
  more: 0,
  computed_at: now,
};
const kpi = { ...base, kind: 'kpi', description: 'Slipping projects', value: 3, total: 3, tasks_total: 3 };
const bar = {
  ...base,
  kind: 'bar',
  description: 'Open tasks waiting on the customer',
  total: 7,
  tasks_total: 7,
  groups: [
    { key: 'p1', label: 'Northwind Health', value: 5, tasks: 5, color: null },
    { key: 'p2', label: 'Bluepeak Logistics', value: 2, tasks: 2, color: null },
  ],
};
const DETAIL = {
  id: 'd-new',
  name: 'My implementations',
  description: null,
  scope: 'workspace',
  project_id: null,
  owner_id: 'u1',
  version: 1,
  can_edit: false,
  widget_count: 1,
  created_at: now,
  updated_at: now,
  widgets: [
    {
      id: 'w-bar',
      kind: 'bar',
      title: 'Waiting on customer',
      query_spec: {},
      viz: { size: 'md' },
      version: 1,
    },
  ],
};

function boot(path: string) {
  const created: Record<string, unknown>[] = [];
  const explained: Record<string, unknown>[] = [];
  const opened: string[] = [];
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    http.get('*/api/v1/dashboards', () => HttpResponse.json({ data: [], meta: { next_cursor: null } })),
    http.get('*/api/v1/dashboards/pinned', () => HttpResponse.json({ data: [] })),
    http.get('*/api/v1/dashboards/:id', () => HttpResponse.json(DETAIL)),
    http.get('*/api/v1/dashboards/widgets/:wid/data', () => HttpResponse.json(bar)),
    http.post('*/api/v1/ai/dashboards/draft', async ({ request }) => {
      const body = (await request.json()) as { text: string };
      if (body.text.includes('Partner'))
        return HttpResponse.json({
          question: 'Which portfolio should the dashboard read?',
          options: ['Customer onboarding'],
          widgets: [],
          notes: [],
          left_out: [],
        });
      return HttpResponse.json({
        question: null,
        options: [],
        name: 'My implementations',
        description: body.text,
        portfolio_id: 'pf-life',
        portfolio: 'Customer onboarding',
        filters: { portfolio_id: 'pf-life', owner: ['me'] },
        widgets: [
          {
            kind: 'kpi',
            title: 'Slipping projects',
            query_spec: { version: 2, entity: 'projects' },
            viz: { size: 'sm' },
            result: kpi,
          },
          {
            kind: 'bar',
            title: 'Waiting on customer',
            query_spec: { version: 2, entity: 'tasks' },
            viz: { size: 'md' },
            result: bar,
          },
        ],
        notes: [],
        left_out: ['NPS by customer'],
      });
    }),
    http.post('*/api/v1/dashboards/from-draft', async ({ request }) => {
      created.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(
        {
          data: DETAIL,
          meta: { activity_id: '01a0ccaf-0000-7000-8000-00000000e101', batch_id: null, version: 1 },
        },
        { status: 201 },
      );
    }),
    http.post('*/api/v1/ai/dashboards/widgets/:wid/explain', async ({ request, params }) => {
      explained.push({ widget: params.wid, ...((await request.json()) as object) });
      return HttpResponse.json({
        widget_id: 'w-bar',
        title: 'Waiting on customer',
        paragraphs: [{ text: 'Northwind Health has 5 of the 7 tasks waiting.', cites: ['Northwind Health'] }],
        links: [{ kind: 'task', id: 't7', label: 'T-7 Send the data template' }],
        sample_label: 'Northwind Health',
        ai: true,
      });
    }),
    http.get('*/api/v1/tasks/:id', ({ params }) => {
      opened.push(params.id as string);
      return HttpResponse.json({ detail: 'not in this test' }, { status: 404 });
    }),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return { created, explained, opened, user: userEvent.setup() };
}

describe('Mo on dashboards (S75-10)', () => {
  it('drafts a dashboard from a sentence with real numbers, and creates it only on Create', async () => {
    const { created, user } = boot('/dashboards');
    await user.click(await screen.findByRole('button', { name: /New with Mo/ }));
    const dialog = await screen.findByRole('dialog', { name: 'New dashboard with Mo' });
    await user.type(
      within(dialog).getByLabelText('What should it show?'),
      'A control tower for Partner rollouts',
    );
    await user.click(within(dialog).getByRole('button', { name: /Draft it/ }));
    expect(await within(dialog).findByText(/Which portfolio/)).toBeInTheDocument();
    expect(within(dialog).getByText('Options: Customer onboarding')).toBeInTheDocument();

    const box = within(dialog).getByLabelText('What should it show?');
    await user.clear(box);
    await user.type(box, 'My implementations: slipping and waiting on customer, and NPS');
    await user.click(within(dialog).getByRole('button', { name: /Draft it/ }));
    const draft = await within(dialog).findByRole('region', { name: 'Draft dashboard' });
    expect(within(draft).getByText('Slipping projects')).toBeInTheDocument();
    expect(within(draft).getByText('3')).toBeInTheDocument(); // the KPI's real number
    expect(within(draft).getByText('2 groups')).toBeInTheDocument();
    expect(within(draft).getByText(/Not shown: NPS by customer/)).toBeInTheDocument();
    expect(created).toHaveLength(0);
    await user.click(within(draft).getByRole('button', { name: 'Create dashboard' }));
    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      name: 'My implementations',
      prompt: 'My implementations: slipping and waiting on customer, and NPS',
      filters: { owner: ['me'] },
    });
    expect((created[0]!.widgets as unknown[]).length).toBe(2);
    expect(await screen.findByText(/Created “My implementations”/)).toBeInTheDocument();
  });

  it('explains a chart for someone who can only view it, with links to the tasks', async () => {
    const { explained, user } = boot('/dashboards/d-new');
    await screen.findByRole('region', { name: 'Waiting on customer' });
    await user.click(screen.getByRole('button', { name: 'Waiting on customer: options' }));
    expect(screen.queryByRole('menuitem', { name: /Edit chart/ })).toBeNull();
    await user.click(await screen.findByRole('menuitem', { name: /Explain/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Explain: Waiting on customer' });
    expect(await within(dialog).findByText(/5 of the 7 tasks waiting/)).toHaveClass('text-amber-ink');
    expect(within(dialog).getByText(/Open the tasks \(Northwind Health\)/)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'T-7 Send the data template' })).toBeInTheDocument();
    expect(explained[0]).toMatchObject({ widget: 'w-bar' });
  });
});
