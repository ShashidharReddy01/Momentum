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
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const RAVI = '01a0ccaf-8f68-77d2-a888-584ea1e80ea8';
const T12 = { ref: '[T-12]', type: 'task', valid: true, id: 'task-12', key: 'T-12', title: 'Pricing copy' };

const HISTORY = [
  {
    id: 'su-1',
    entity_type: 'project',
    entity_id: 'seed-1',
    status: 'at_risk',
    title: 'Pricing slips',
    summary: 'Copy is late [T-12].',
    sections: { completed: [], slipped: [{ text: 'Pricing copy [T-12]' }], blockers: [], next: [] },
    author_id: RAVI,
    generated_by_ai: true,
    created_at: new Date().toISOString(),
    citations: [T12],
  },
];

const DRAFT = {
  draft: {
    status: 'on_track',
    title: 'Steady week',
    summary: 'Finished [T-12].',
    sections: { completed: [{ text: 'Finished the copy [T-12]' }], slipped: [], blockers: [], next: [] },
    generated_by_ai: true,
  },
  notes: ['Removed from Slipped: “Something vague” cites no task.'],
  facts: { completed: 1, overdue: 0, pushed: 0, blocked: 0, due_soon: 0 },
  since: '2026-09-19',
  citations: [T12],
};

function boot(opts: { role?: string; aiEnabled?: boolean; path?: string; history?: unknown[] } = {}) {
  const posted: unknown[] = [];
  let drafts = 0;
  server.use(
    ...authHandlers({ loggedIn: true, config: { ai_enabled: opts.aiEnabled ?? true } }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: opts.role ?? 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    http.get('*/api/v1/projects/:id/status-updates', () =>
      HttpResponse.json({ data: opts.history ?? HISTORY, meta: { next_cursor: null } }),
    ),
    http.post('*/api/v1/projects/:id/status-updates', async ({ request }) => {
      const body = await request.json();
      posted.push(body);
      return HttpResponse.json(
        {
          data: { ...HISTORY[0], ...(body as object), id: 'su-2', citations: [] },
          meta: { activity_id: '01a0ccaf-0000-7000-8000-00000000c001', batch_id: null, version: 2 },
        },
        { status: 201 },
      );
    }),
    http.post('*/api/v1/ai/projects/:id/status-draft', () => {
      drafts += 1;
      return HttpResponse.json(DRAFT);
    }),
  );
  window.history.replaceState(null, '', opts.path ?? '/projects/seed-1/overview');
  render(<MomentumApp />);
  return { posted, drafts: () => drafts, user: userEvent.setup() };
}

describe('Status updates (S3.4.3)', () => {
  it('Overview shows the history with status, AI mark and working citations', async () => {
    boot();
    const card = await screen.findByRole('article', { name: 'Status: Pricing slips' });
    expect(within(card).getByText('At risk')).toBeInTheDocument();
    expect(within(card).getByTitle('Drafted by Mo, edited and posted by a person')).toBeInTheDocument();
    expect(
      within(within(card).getByRole('region', { name: 'Slipped' })).getByRole('link', {
        name: 'T-12 Pricing copy',
      }),
    ).toHaveAttribute('href', '/task/task-12');
  });

  it('Draft with Mo → edit → post (marked as AI-drafted) with an undo toast', async () => {
    const { user, posted } = boot();
    await user.click(await screen.findByRole('button', { name: /Draft with Mo/ }));
    const callout = await screen.findByRole('region', { name: 'Mo’s draft (AI)' });
    expect(within(callout).getByRole('list', { name: 'Mo left out' })).toHaveTextContent('cites no task');
    const headline = within(callout).getByRole('textbox', { name: 'Headline' });
    expect(headline).toHaveValue('Steady week');
    expect(within(callout).getByRole('textbox', { name: 'Completed' })).toHaveValue(
      'Finished the copy [T-12]',
    );
    await user.clear(headline);
    await user.type(headline, 'Great week');
    await user.type(within(callout).getByRole('textbox', { name: 'Next' }), 'Launch [[T-12]');
    await user.click(within(callout).getByRole('button', { name: 'Post update' }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({
      status: 'on_track',
      title: 'Great week',
      summary: 'Finished [T-12].',
      sections: {
        completed: [{ text: 'Finished the copy [T-12]' }],
        slipped: [],
        blockers: [],
        next: [{ text: 'Launch [T-12]' }],
      },
      generated_by_ai: true,
    });
    expect(await screen.findByText('Status update posted')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Mo’s draft (AI)' })).toBeNull();
  });

  it('a hand-written update is not marked as AI; discard posts nothing', async () => {
    const { user, posted } = boot({ history: [] });
    expect(await screen.findByText('No status updates yet')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Post update' }));
    const form = screen.getByRole('form', { name: 'Status update' });
    await user.selectOptions(within(form).getByRole('combobox'), 'off_track');
    await user.type(within(form).getByRole('textbox', { name: 'Headline' }), 'Stuck');
    await user.type(within(form).getByRole('textbox', { name: 'Blockers' }), '- Vendor\n- Legal');
    await user.click(within(form).getByRole('button', { name: 'Post update' }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({
      status: 'off_track',
      title: 'Stuck',
      generated_by_ai: false,
      sections: { blockers: [{ text: 'Vendor' }, { text: 'Legal' }] },
    });
  });

  it('the header "Draft status" opens Overview with the draft requested', async () => {
    const { user, drafts } = boot({ path: '/projects/seed-1/list' });
    await user.click(await screen.findByRole('button', { name: /Draft status/ }));
    expect(await screen.findByRole('region', { name: 'Mo’s draft (AI)' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/projects/seed-1/overview');
    expect(drafts()).toBe(1);
  });

  it('viewers only read; with AI off there is no Mo draft', async () => {
    boot({ role: 'viewer' });
    await screen.findByRole('article', { name: 'Status: Pricing slips' });
    expect(screen.queryByRole('button', { name: 'Post update' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Draft/ })).toBeNull();
  });

  it('AI off: Post update only', async () => {
    boot({ aiEnabled: false });
    await screen.findByRole('article', { name: 'Status: Pricing slips' });
    expect(screen.getByRole('button', { name: 'Post update' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Draft with Mo|Draft status/ })).toBeNull();
  });
});
