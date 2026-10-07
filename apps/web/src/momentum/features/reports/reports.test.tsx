import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { fileHandlers } from '@/mocks/files';
import { authHandlers } from '@/mocks/handlers';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const now = new Date().toISOString();

function boot() {
  const previews: Record<string, unknown>[] = [];
  const created: Record<string, unknown>[] = [];
  const statuses: Record<string, unknown>[] = [];
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...notificationHandlers(),
    ...fileHandlers([]).handlers,
    http.post('*/api/v1/reports/preview', async ({ request }) => {
      const body = (await request.json()) as { spec: Record<string, unknown> };
      previews.push(body.spec);
      const customer = body.spec.kind === 'customer_status';
      return HttpResponse.json({
        title: customer ? 'Website Revamp: progress update' : 'Website Revamp: status',
        subtitle: '01 Oct 2026 to 07 Oct 2026',
        scope_note: 'Includes what Ravi Kumar could see on 07 Oct 2026.',
        items: [
          { type: 'kpis', title: 'Progress 40%, Overdue 2' },
          ...(body.spec.narrative
            ? [{ type: 'narrative', title: 'AI-drafted summary (marked, review before sending)' }]
            : []),
          { type: 'table', title: 'Milestones', rows: 3 },
        ],
        pages: 2,
        sheets: null,
      });
    }),
    http.post('*/api/v1/ai/projects/:pid/closeout-status', () =>
      HttpResponse.json({
        project_id: 'seed-1',
        project: 'Website Revamp',
        ai: true,
        status_update: {
          status: 'complete',
          title: 'Close-out: Website Revamp',
          summary: 'The launch shipped [T-3]; pricing slipped a week [T-7].',
          sections: {
            completed: [],
            slipped: [{ text: 'Pricing finished 7 days late' }],
            blockers: [],
            next: [],
          },
          generated_by_ai: true,
        },
      }),
    ),
    http.post('*/api/v1/projects/:pid/status-updates', async ({ request }) => {
      statuses.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(
        { data: { id: 'su-1' }, meta: { activity_id: '01a0ccaf-0000-7000-8000-00000000f002', version: 1 } },
        { status: 201 },
      );
    }),
    http.post('*/api/v1/reports', async ({ request }) => {
      const body = (await request.json()) as { spec: Record<string, unknown> };
      created.push(body.spec);
      return HttpResponse.json(
        {
          id: 'run-1',
          kind: body.spec.kind,
          status: 'done',
          attachment_id: 'att-9',
          filename: 'Website Revamp - Customer update 2026-10-07.docx',
          project_id: 'seed-1',
          portfolio_id: null,
          error: null,
          activity_id: '01a0ccaf-0000-7000-8000-00000000f001',
          created_at: now,
          finished_at: now,
        },
        { status: 202 },
      );
    }),
  );
  window.history.replaceState(null, '', '/projects/seed-1/list');
  render(<MomentumApp />);
  return { previews, created, statuses, user: userEvent.setup() };
}

describe('Create report (Phase 7.5)', () => {
  it('previews the outline, then makes the file and offers it with Undo', async () => {
    const { previews, created, user } = boot();
    await user.click(await screen.findByRole('button', { name: 'Project actions' }));
    await user.click(await screen.findByRole('menuitem', { name: /Create report/ }));
    const dialog = await screen.findByRole('dialog', { name: /Create a report: Website Revamp/ });
    const outline = within(dialog).getByRole('region', { name: 'Report outline' });
    expect(await within(outline).findByText('Progress 40%, Overdue 2')).toBeInTheDocument();
    expect(within(outline).getByText(/AI-drafted summary/)).toHaveClass('text-amber-ink');
    expect(within(outline).getByText('About 2 pages')).toBeInTheDocument();
    expect(previews[0]).toMatchObject({ kind: 'project_status', format: 'docx', narrative: true });

    // a customer update: the format list follows the kind, and the audience is the customer
    await user.click(within(dialog).getByRole('button', { name: /Customer update/ }));
    expect(within(dialog).getByText(/tasks tagged “internal”/)).toBeInTheDocument();
    expect(within(dialog).queryByRole('radio', { name: 'Markdown' })).toBeNull();
    await waitFor(() =>
      expect(previews.at(-1)).toMatchObject({ kind: 'customer_status', audience: 'customer' }),
    );
    await user.click(within(dialog).getByRole('button', { name: 'Create report' }));
    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({ kind: 'customer_status', scope: { project_id: 'seed-1' } });
    const ready = await within(dialog).findByRole('status');
    expect(ready).toHaveTextContent('Website Revamp - Customer update 2026-10-07.docx');
    expect(within(ready).getByRole('link', { name: /Download/ })).toHaveAttribute(
      'href',
      '/api/v1/attachments/att-9/download',
    );
    expect(await screen.findByText(/Report ready: Website Revamp/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
  });

  it('a task export comes as Excel or CSV, with no period or summary', async () => {
    const { previews, user } = boot();
    await user.click(await screen.findByRole('button', { name: 'Project actions' }));
    await user.click(await screen.findByRole('menuitem', { name: /Create report/ }));
    const dialog = await screen.findByRole('dialog', { name: /Create a report/ });
    await user.click(within(dialog).getByRole('button', { name: /Task export/ }));
    expect(within(dialog).getByRole('radio', { name: 'Excel' })).toHaveAttribute('aria-checked', 'true');
    expect(within(dialog).queryByLabelText('Period')).toBeNull();
    expect(within(dialog).queryByLabelText('Add Mo’s summary')).toBeNull();
    await waitFor(() => expect(previews.at(-1)).toMatchObject({ kind: 'task_export', format: 'xlsx' }));
    expect(previews.at(-1)).not.toHaveProperty('period');
  });

  it('close-out: from the menu, then the final status update after a preview (S75-12)', async () => {
    const { created, statuses, user } = boot();
    await user.click(await screen.findByRole('button', { name: 'Project actions' }));
    await user.click(await screen.findByRole('menuitem', { name: /Create close-out report/ }));
    const dialog = await screen.findByRole('dialog', { name: /Create a report: Website Revamp/ });
    expect(within(dialog).getByRole('button', { name: /Close-out/ })).toHaveAttribute('aria-pressed', 'true');
    await user.click(within(dialog).getByRole('button', { name: 'Create report' }));
    await waitFor(() => expect(created[0]).toMatchObject({ kind: 'closeout' }));
    await user.click(await within(dialog).findByRole('button', { name: 'Post as status update…' }));
    const preview = await within(dialog).findByRole('region', { name: 'Close-out status update' });
    expect(within(preview).getByText(/The launch shipped/)).toHaveClass('text-amber-ink');
    expect(statuses).toHaveLength(0);
    await user.click(within(preview).getByRole('button', { name: 'Post status update' }));
    await waitFor(() => expect(statuses[0]).toMatchObject({ status: 'complete', generated_by_ai: true }));
    expect(await within(dialog).findByText('The close-out status update is posted.')).toBeInTheDocument();
  });
});
