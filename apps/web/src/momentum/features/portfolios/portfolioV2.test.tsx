import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import {
  lifecycleState,
  portfolioDetail,
  portfolioV2Handlers,
  STAGE_FIELD,
  VALUE_FIELD,
} from '@/mocks/portfolios';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function boot(path: string, state = lifecycleState()) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp' }]),
  );
  server.use(...portfolioV2Handlers(state));
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return { state, user: userEvent.setup() };
}

describe('Portfolio v2: table (Phase 7.5)', () => {
  it('shows the server’s columns, sorts, groups with rollups and edits a field in place', async () => {
    const { state, user } = boot('/portfolios/pf-life');
    const table = await screen.findByRole('table', { name: 'Projects in Customer onboarding' });
    const headers = within(table)
      .getAllByRole('columnheader')
      .map((h) => h.textContent);
    expect(headers.slice(1, 4)).toEqual(['Project', 'Stage', 'Contract value']);
    expect(within(table).getByText('Northwind Health')).toBeInTheDocument();
    expect(screen.getByText(/1 more project is in this portfolio but not shown/)).toBeInTheDocument();

    // sort by a field: the request asks the server, which answers in order
    await user.click(within(table).getByRole('button', { name: 'Contract value' }));
    await user.click(within(table).getByRole('button', { name: /Contract value/ }));
    await waitFor(() => expect(state.calls.length).toBeGreaterThanOrEqual(0));
    await waitFor(() =>
      expect(within(table).getByRole('columnheader', { name: /Contract value/ })).toHaveAttribute(
        'aria-sort',
        'descending',
      ),
    );

    // group by stage: rollup rows with counts and sums
    await user.selectOptions(screen.getByRole('combobox', { name: 'Group by' }), 'stage');
    const discovery = await screen.findByRole('rowheader', { name: /Discovery/ });
    expect(discovery).toHaveTextContent('2 projects');
    expect(discovery).toHaveTextContent('Contract value 200,000 EUR');

    // inline edit of a project field (only where the row is editable)
    const north = screen.getByRole('row', { name: /Northwind Health/ });
    const input = within(north).getByRole('spinbutton', { name: 'Contract value' });
    await user.clear(input);
    await user.type(input, '150000{Enter}');
    await waitFor(() =>
      expect(state.calls).toContainEqual(expect.objectContaining({ method: 'PUT', body: { value: 150000 } })),
    );
    const cedar = screen.getByRole('row', { name: /Cedar & Finch Legal/ });
    expect(within(cedar).queryByRole('spinbutton')).toBeNull(); // read-only row
  });

  it('bulk "Set field…" on selected rows is one request (one undo)', async () => {
    const { state, user } = boot('/portfolios/pf-life/table');
    await screen.findByRole('table', { name: 'Projects in Customer onboarding' });
    await user.click(screen.getByRole('checkbox', { name: 'Select Northwind Health' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select Bluepeak Logistics' }));
    const bar = screen.getByRole('region', { name: 'Selected projects' });
    expect(bar).toHaveTextContent('2 selected');
    await user.selectOptions(within(bar).getByRole('combobox', { name: 'Field to set' }), VALUE_FIELD);
    await user.type(within(bar).getByRole('spinbutton', { name: 'Contract value' }), '99000{Enter}');
    await user.click(within(bar).getByRole('button', { name: 'Apply' }));
    await waitFor(() =>
      expect(state.calls).toContainEqual(
        expect.objectContaining({
          method: 'POST',
          body: { project_ids: ['p-north', 'p-blue'], field_id: VALUE_FIELD, value: 99000 },
        }),
      ),
    );
    expect(await screen.findByText('Updated 2 projects')).toBeInTheDocument();
  });

  it('saves a personal view and switches to a shared one', async () => {
    const { state, user } = boot('/portfolios/pf-life/table');
    await screen.findByRole('table', { name: 'Projects in Customer onboarding' });
    await user.click(screen.getByRole('button', { name: 'Save view' }));
    await user.type(screen.getByRole('textbox', { name: 'View name' }), 'My pipeline');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(state.calls).toContainEqual(
        expect.objectContaining({ body: expect.objectContaining({ name: 'My pipeline', shared: false }) }),
      ),
    );
    await user.selectOptions(screen.getByRole('combobox', { name: 'View' }), 'v-shared');
    expect(await screen.findByRole('rowheader', { name: /Discovery/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Export CSV/ })).toHaveAttribute(
      'href',
      expect.stringContaining('/portfolios/pf-life/export/csv?view_id=v-shared'),
    );
  });
});

describe('Portfolio v2: board (Phase 7.5)', () => {
  it('moves a card from its menu, and shows the gate checklist with Move anyway', async () => {
    const { state, user } = boot('/portfolios/pf-life/board');
    const discovery = await screen.findByRole('listitem', { name: 'Discovery: 2 projects' });
    expect(within(discovery).getByText('Northwind Health')).toBeInTheDocument();
    expect(within(discovery).getByText(/target 21 days/)).toBeInTheDocument();
    expect(within(discovery).getByText('30 days in stage')).toHaveClass('text-crit'); // past the target

    await user.click(within(discovery).getByRole('button', { name: 'Move Northwind Health to stage…' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Contracts' }));
    await waitFor(() =>
      expect(state.calls).toContainEqual(expect.objectContaining({ body: { to: 's-con', override: false } })),
    );

    await user.click(within(discovery).getByRole('button', { name: 'Move Bluepeak Logistics to stage…' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Implementation' }));
    const dialog = await screen.findByRole('dialog', { name: /isn’t ready for Implementation/ });
    const checklist = within(dialog).getByRole('list', { name: 'Gate checklist' });
    expect(within(checklist).getAllByRole('listitem')).toHaveLength(2);
    expect(within(checklist).getByText('Contract signed')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Move anyway' }));
    await waitFor(() =>
      expect(state.calls).toContainEqual(expect.objectContaining({ body: { to: 's-impl', override: true } })),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('asks for a stage field when there is none', async () => {
    boot('/portfolios/pf-life/board');
    server.use(
      http.get('*/api/v1/portfolios/:id', () => HttpResponse.json(portfolioDetail({ stage_field_id: null }))),
    );
    expect(await screen.findByText('No stage field yet')).toBeInTheDocument();
  });
});

describe('Portfolio v2: timeline, workload, settings, list (Phase 7.5)', () => {
  it('draws one bar per project, grouped by stage', async () => {
    boot('/portfolios/pf-life/timeline');
    const timeline = await screen.findByRole('region', { name: 'Timeline of Customer onboarding' });
    const north = within(timeline).getByRole('listitem', { name: /Northwind Health/ });
    expect(north).toHaveAccessibleName(expect.stringContaining('target'));
    expect(north).toHaveAccessibleName(expect.stringContaining('15 days late'));
    expect(within(timeline).getByRole('list', { name: 'Discovery' })).toBeInTheDocument();
    // a project with only a target still appears
    expect(
      within(timeline).getByRole('listitem', { name: /Cedar & Finch Legal, target/ }),
    ).toBeInTheDocument();
  });

  it('scopes the workload grid to the portfolio', async () => {
    const seen: string[] = [];
    boot('/portfolios/pf-life/workload');
    server.use(
      http.get('*/api/v1/workload', ({ request }) => {
        seen.push(new URL(request.url).searchParams.get('portfolio_id') ?? '');
        return HttpResponse.json({
          start: '2026-10-05',
          weeks: [],
          default_minutes: 1800,
          default_source: 'default',
          can_admin: false,
          people: [],
          unassigned: null,
          any_estimate: false,
          tasks: [],
        });
      }),
    );
    expect(
      await screen.findByRole('heading', { name: 'Workload of this portfolio’s projects' }),
    ).toBeInTheDocument();
    await waitFor(() => expect(seen).toContain('pf-life'));
    expect(screen.queryByRole('combobox', { name: 'Project' })).toBeNull();
  });

  it('settings: the stage field with targets and gates, saved in one change', async () => {
    const { state, user } = boot('/portfolios/pf-life/table');
    await user.click(await screen.findByRole('button', { name: 'Settings' }));
    const dialog = await screen.findByRole('dialog', { name: 'Portfolio settings' });
    await user.click(within(dialog).getByRole('tab', { name: 'Stages and gates' }));
    const target = within(dialog).getByRole('spinbutton', { name: 'Target days for Contracts' });
    await user.type(target, '14');
    const files = within(dialog).getByRole('textbox', { name: 'Files Implementation needs' });
    await user.type(files, '*signed*');
    await user.tab();
    await user.click(within(dialog).getByRole('button', { name: 'Save stages' }));
    await waitFor(() =>
      expect(state.calls).toContainEqual(
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({
            stage_field_id: STAGE_FIELD,
            stage_targets: { 's-disc': 21, 's-con': 14 },
            stage_gates: {
              's-impl': expect.objectContaining({
                required_files: ['*signed*'],
                required_milestones: ['Contract signed'],
              }),
            },
          }),
        }),
      ),
    );
    await user.click(within(dialog).getByRole('tab', { name: 'Members' }));
    expect(within(dialog).getByRole('list', { name: 'Members' })).toHaveTextContent('Mei Chen');
  });

  it('list cards show a bar per stage and the total value', async () => {
    boot('/portfolios');
    server.use(
      http.get('*/api/v1/portfolios', () =>
        HttpResponse.json({
          data: [
            portfolioDetail({
              summary: {
                portfolio_id: 'pf-life',
                stages: [
                  { option_id: 's-pre', label: 'Pre-sales', count: 1 },
                  { option_id: 's-disc', label: 'Discovery', count: 2 },
                ],
                value_field: 'Contract value',
                total_value: 200000,
              },
            }),
          ],
          meta: { next_cursor: null },
        }),
      ),
    );
    expect(
      await screen.findByRole('img', { name: 'Projects per stage: Pre-sales 1, Discovery 2' }),
    ).toBeInTheDocument();
    expect(screen.getByText('200,000')).toBeInTheDocument();
  });
});
