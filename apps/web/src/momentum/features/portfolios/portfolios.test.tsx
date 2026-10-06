import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { addDays, toISODate } from '@/lib/dates';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const iso = (days: number) => toISODate(addDays(new Date(), days));
const row = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  color: 'proj-3',
  owner_id: null,
  status: null,
  total_tasks: 10,
  completed_tasks: 4,
  overdue_tasks: 0,
  start_on: null,
  due_on: null,
  latest_update_title: null,
  latest_update_at: null,
  ...extra,
});
const DETAIL = {
  id: 'pf-1',
  name: 'Q4 launches',
  description: 'Everything shipping this quarter',
  owner_id: 'u1',
  status: null,
  version: 3,
  can_edit: true,
  project_count: 2,
  created_at: new Date().toISOString(),
  projects: [
    row('p1', 'Website Revamp', {
      status: 'at_risk',
      overdue_tasks: 2,
      due_on: iso(9),
      latest_update_title: 'Vendor is late',
      latest_update_at: new Date().toISOString(),
    }),
    row('p2', 'Mobile App', { status: 'on_track', completed_tasks: 9 }),
  ],
  hidden_projects: 1,
};

function boot(detail = DETAIL) {
  const posted: unknown[] = [];
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp' }]),
  );
  server.use(
    http.get('*/api/v1/portfolios/:id', () => HttpResponse.json(detail)),
    http.get('*/api/v1/portfolios/:id/status-updates', () => HttpResponse.json({ data: [] })),
    http.post('*/api/v1/ai/portfolios/:id/lines', () =>
      HttpResponse.json({
        lines: [
          { project_id: 'p1', text: 'Needs attention: the vendor is late.', ai: true },
          { project_id: 'p2', text: '90% done (9 of 10)', ai: false },
        ],
      }),
    ),
    http.get('*/api/v1/portfolios/:id/status-draft', () =>
      HttpResponse.json({
        draft: {
          status: 'at_risk',
          title: '1 at risk, 1 on track',
          summary: '2 projects',
          sections: {
            slipped: [{ text: 'Website Revamp is at risk: Vendor is late' }],
            completed: [],
            blockers: [],
            next: [],
          },
          generated_by_ai: false,
        },
      }),
    ),
    http.post('*/api/v1/portfolios/:id/status-updates', async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json(
        {
          data: {
            id: 'su1',
            status: 'at_risk',
            title: 'x',
            summary: '',
            sections: {},
            created_at: new Date().toISOString(),
            citations: [],
          },
          meta: { activity_id: 'a1', version: 4 },
        },
        { status: 201 },
      );
    }),
  );
  window.history.replaceState(null, '', '/portfolios/pf-1/overview'); // the S6.2.2 view is the Overview tab
  render(<MomentumApp />);
  return { posted, user: userEvent.setup() };
}

describe('Portfolio page (S6.2.2)', () => {
  it('shows every visible project side by side, a status mix, and Mo’s one-line read', async () => {
    boot();
    const table = await screen.findByRole('table', { name: 'Projects in Q4 launches' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Website Revamp');
    expect(rows[0]).toHaveTextContent('At risk');
    expect(rows[0]).toHaveTextContent('40%');
    expect(rows[0]).toHaveTextContent('2 overdue');
    expect(rows[0]).toHaveTextContent('Vendor is late');
    await waitFor(() =>
      expect(within(rows[0]!).getByText('Needs attention: the vendor is late.')).toHaveClass(
        'text-amber-ink',
      ),
    );
    expect(within(rows[1]!).getByText('90% done (9 of 10)')).toHaveClass('text-muted'); // plain, not AI
    expect(screen.getByRole('region', { name: 'Status mix' })).toHaveTextContent('1 at risk');
    expect(screen.getByText(/1 more project is in this portfolio but not shown/)).toBeInTheDocument();
  });

  it('drafts a check-in from the projects and posts it', async () => {
    const { posted, user } = boot();
    await user.click(await screen.findByRole('button', { name: 'Draft check-in' }));
    const form = await screen.findByRole('form', { name: 'New check-in' });
    expect(within(form).getByRole('textbox', { name: 'Title' })).toHaveValue('1 at risk, 1 on track');
    expect(form).toHaveTextContent('Website Revamp is at risk: Vendor is late');
    await user.click(within(form).getByRole('button', { name: 'Post check-in' }));
    await waitFor(() => expect(posted).toHaveLength(1));
  });

  it('is read-only for someone who is not the owner', async () => {
    boot({ ...DETAIL, can_edit: false });
    await screen.findByRole('table');
    expect(screen.queryByRole('button', { name: 'Add project' })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Remove / })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Draft check-in' })).toBeNull();
  });
});
