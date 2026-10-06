import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { addDays, toISODate } from '@/lib/dates';
import { fieldHandlers } from '@/mocks/fields';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const iso = (days: number) => toISODate(addDays(new Date(), days));

function boot(project: Record<string, unknown>, overview: Record<string, unknown>, role = 'admin') {
  const patches: unknown[] = [];
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: role, ...project }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...fieldHandlers(),
    http.get('*/api/v1/projects/:id/risk', () => HttpResponse.json(null)),
    http.get('*/api/v1/projects/:id/forecast', () => HttpResponse.json({ forecast: null })),
    http.get('*/api/v1/projects/:id/status-updates', () =>
      HttpResponse.json({ data: [], meta: { next_cursor: null } }),
    ),
  );
  // registered last so they win over projectHandlers' defaults
  server.use(
    http.get('*/api/v1/projects/:id/overview', () => HttpResponse.json(overview)),
    http.patch('*/api/v1/projects/:id', async ({ request }) => {
      const body = await request.json();
      patches.push(body);
      return HttpResponse.json({
        data: { id: 'seed-1', ...(body as object) },
        meta: { activity_id: '01a0ccaf-0000-7000-8000-00000000d001', batch_id: null, version: 2 },
      });
    }),
  );
  window.history.replaceState(null, '', '/projects/seed-1/overview');
  render(<MomentumApp />);
  return { patches, user: userEvent.setup() };
}

const OVERVIEW = {
  total_tasks: 20,
  completed_tasks: 8,
  overdue_tasks: 2,
  milestones: [
    {
      id: 'm1',
      key: 'T-3',
      title: 'Design signed off',
      due_on: iso(-4),
      completed_at: new Date().toISOString(),
    },
    { id: 'm2', key: 'T-9', title: 'Beta ships', due_on: iso(12), completed_at: null },
  ],
};

describe('Project overview (S6.2.1)', () => {
  it('sums the project up at a glance: status, progress, dates, next milestone', async () => {
    boot({ status: 'at_risk', due_on: iso(30), start_on: iso(-10) }, OVERVIEW);
    const summary = await screen.findByRole('region', { name: 'Summary' });
    expect(within(summary).getByRole('group', { name: 'Status' })).toHaveTextContent('At risk');
    const progress = within(summary).getByRole('group', { name: 'Progress' });
    await waitFor(() => expect(progress).toHaveTextContent('40%'));
    expect(progress).toHaveTextContent('8 of 20 tasks done');
    expect(progress).toHaveTextContent('2 overdue');
    expect(within(summary).getByRole('group', { name: 'Dates' })).toHaveTextContent('30 days left');
    const next = within(summary).getByRole('group', { name: 'Next milestone' });
    expect(next).toHaveTextContent('Beta ships');
    expect(next).toHaveTextContent('in 12 days');
    const milestones = screen.getByRole('complementary', { name: 'Details, milestones and members' });
    expect(within(milestones).getByRole('button', { name: 'Design signed off' })).toHaveClass('line-through');
    expect(within(milestones).getByText('Ravi Kumar')).toBeInTheDocument();
  });

  it('says what is missing instead of inventing it, and lets an editor set the due date', async () => {
    const { patches, user } = boot(
      {},
      { total_tasks: 0, completed_tasks: 0, overdue_tasks: 0, milestones: [] },
    );
    const summary = await screen.findByRole('region', { name: 'Summary' });
    expect(within(summary).getByRole('group', { name: 'Status' })).toHaveTextContent('No status posted yet');
    await waitFor(() =>
      expect(within(summary).getByRole('group', { name: 'Progress' })).toHaveTextContent('No tasks yet'),
    );
    expect(within(summary).getByRole('group', { name: 'Next milestone' })).toHaveTextContent(
      'No milestones yet',
    );

    await user.click(within(summary).getByRole('button', { name: 'Due date: not set' }));
    await user.click(await screen.findByRole('button', { name: 'Tomorrow' }));
    await waitFor(() => expect(patches).toEqual([{ due_on: iso(1) }]));
  });

  it('is read-only for a viewer', async () => {
    boot({ due_on: iso(5) }, OVERVIEW, 'viewer');
    const summary = await screen.findByRole('region', { name: 'Summary' });
    expect(within(summary).queryByRole('button', { name: /^Due date/ })).toBeNull();
    expect(screen.getByText('No brief yet.')).toBeInTheDocument();
  });
});

describe('Project overview: Details (Phase 7.5, project fields)', () => {
  it('starts empty, lets an editor add a project field and set it, with undo', async () => {
    const { user } = boot({}, OVERVIEW);
    const details = await screen.findByRole('region', { name: 'Details' });
    expect(await within(details).findByText(/No project fields yet/)).toBeInTheDocument();

    await user.click(within(details).getByRole('button', { name: 'Add a project field' }));
    await user.type(within(details).getByRole('textbox', { name: 'New field name' }), 'Stage');
    await user.selectOptions(within(details).getByRole('combobox', { name: 'Field type' }), 'single_select');
    await user.type(within(details).getByRole('textbox', { name: 'Option 1' }), 'Discovery');
    await user.type(within(details).getByRole('textbox', { name: 'Option 2' }), 'Implementation');
    await user.click(within(details).getByRole('button', { name: 'Add field' }));

    await user.click(await within(details).findByRole('button', { name: 'Stage' }));
    await user.click(await screen.findByRole('option', { name: 'Implementation' }));
    await waitFor(() =>
      expect(within(details).getByRole('button', { name: 'Stage' })).toHaveTextContent('Implementation'),
    );
    expect(await screen.findByText('Stage updated')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Undo' }).length).toBeGreaterThan(0);
  });

  it('shows values read-only to a viewer and says "Not set" for an empty one', async () => {
    boot({}, OVERVIEW, 'viewer');
    server.use(
      http.get('*/api/v1/project-fields', () =>
        HttpResponse.json({
          data: [
            {
              id: 'pf-1',
              name: 'Contract value',
              type: 'currency',
              options: { precision: 0, unit: 'EUR' },
              description: null,
              is_library: true,
              created_by: null,
              applies_to: 'project',
            },
            {
              id: 'pf-2',
              name: 'Account',
              type: 'text',
              options: null,
              description: null,
              is_library: true,
              created_by: null,
              applies_to: 'project',
            },
          ],
          meta: { next_cursor: null },
        }),
      ),
      http.get('*/api/v1/projects/:id/project-field-values', () =>
        HttpResponse.json({
          data: [{ field_id: 'pf-1', value: 48000, updated_at: new Date().toISOString(), updated_by: null }],
          meta: { next_cursor: null },
        }),
      ),
    );
    const details = await screen.findByRole('region', { name: 'Details' });
    await waitFor(() => expect(details).toHaveTextContent('48000 EUR'));
    expect(details).toHaveTextContent('Not set');
    expect(within(details).queryByRole('button', { name: 'Add a project field' })).toBeNull();
    expect(within(details).queryByRole('textbox')).toBeNull();
  });
});
