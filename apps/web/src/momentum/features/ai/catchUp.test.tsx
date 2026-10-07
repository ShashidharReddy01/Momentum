import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { homeHandlers } from '@/mocks/home';
import { onboardingHandlers } from '@/mocks/onboarding';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

const since = '2026-10-04T09:00:00Z';

function boot(path: string, opts: { quiet?: boolean } = {}) {
  const asked: Record<string, unknown>[] = [];
  const visits: Record<string, unknown>[] = [];
  server.use(
    http.get('*/api/v1/ai/catch-up/pending', () =>
      HttpResponse.json({
        since,
        total: 5,
        counts: { reassigned_to_me: 1, completed: 3, mentions: 1 },
        show_card: true,
      }),
    ),
    http.put('*/api/v1/visits', async ({ request }) => {
      visits.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ last_seen_at: new Date().toISOString() });
    }),
    http.post('*/api/v1/ai/catch-up', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      asked.push(body);
      if (opts.quiet)
        return HttpResponse.json({
          scope: 'the project Website Revamp',
          since,
          total: 0,
          counts: {},
          nothing_changed: true,
          lines: [],
          ai: false,
        });
      return HttpResponse.json({
        scope: 'everything you can see',
        since,
        total: 5,
        counts: { reassigned_to_me: 1, completed: 3, mentions: 1 },
        nothing_changed: false,
        lines: [
          { text: 'Ana gave you the press kit [T-14].', cites: ['T-14'], task_ids: ['t14'] },
          { text: 'Ana finished three launch tasks.', cites: ['T-3'], task_ids: ['t3'] },
        ],
        ai: true,
      });
    }),
    ...authHandlers({ loggedIn: true }).handlers,
    ...homeHandlers('', {
      has_projects: true,
      counts: { open: 3, due_today: 0, overdue: 0 },
    }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...onboardingHandlers(''),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return { asked, visits, user: userEvent.setup() };
}

describe('Catch me up (S75-11)', () => {
  it('shows "While you were away" on Home, catches up and can be dismissed', async () => {
    const { asked, user } = boot('/');
    const card = await screen.findByRole('region', { name: 'While you were away' });
    expect(card).toHaveTextContent('5 changes since');
    expect(card).toHaveTextContent('1 reassigned to you');
    await user.click(within(card).getByRole('button', { name: 'Catch me up' }));
    const dialog = await screen.findByRole('dialog', { name: 'While you were away' });
    const list = await within(dialog).findByRole('list', { name: 'What changed' });
    expect(within(list).getByText('Ana gave you the press kit [T-14].')).toBeInTheDocument();
    expect(within(list).getAllByRole('listitem')[0]).toHaveClass('text-amber-ink');
    expect(asked[0]).toMatchObject({ scope: 'home' });
    await user.click(within(dialog).getByRole('button', { name: 'Done' }));
    await user.click(within(card).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'While you were away' })).toBeNull());
  });

  it('a project with nothing new says so, without Mo', async () => {
    const { asked, user } = boot('/projects/seed-1/list', { quiet: true });
    await user.click(await screen.findByRole('button', { name: /Catch me up/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Catch me up: Website Revamp' });
    expect(await within(dialog).findByText(/Nothing changed since/)).toBeInTheDocument();
    expect(asked[0]).toMatchObject({ scope: 'project', scope_id: 'seed-1' });
  });
});
