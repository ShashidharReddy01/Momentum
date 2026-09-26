import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { homeHandlers, homeTask } from '@/mocks/home';
import { onboardingHandlers } from '@/mocks/onboarding';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';
import type { components } from '@/lib/api/schema';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

function boot(
  home: Partial<components['schemas']['HomeOut']>,
  onboarding: Parameters<typeof onboardingHandlers>[1] = {},
) {
  const h = homeHandlers('', home);
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...h.handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers(),
    ...onboardingHandlers('', onboarding),
  );
  window.history.replaceState(null, '', '/');
  render(<MomentumApp />);
  return { user: userEvent.setup(), ...h };
}

const project = (name: string, extra: Partial<components['schemas']['HomeProjectOut']> = {}) => ({
  id: `p-${name}`,
  name,
  color: 'proj-6',
  team_id: 'team-x',
  team_name: 'Product',
  open_count: 12,
  overdue_count: 0,
  last_active_at: new Date().toISOString(),
  ...extra,
});

describe('Home', () => {
  it('greets, summarises, and shows priorities, waiting and recent projects', async () => {
    boot({
      priorities: [homeTask('Fix the login bug', -2), homeTask('Write release notes', 0)],
      counts: { open: 9, due_today: 1, overdue: 1 },
      waiting: [homeTask('Vendor contract', -3, { assignee_id: 'someone-else' })],
      waiting_total: 4,
      recent_projects: [project('Website Revamp', { overdue_count: 2 }), project('Mobile App v2')],
    });
    expect(
      await screen.findByRole('heading', { level: 1, name: /Good (morning|afternoon|evening)/ }),
    ).toBeInTheDocument();
    expect(await screen.findByText('1 task overdue · 1 due today')).toBeInTheDocument();
    const priorities = screen.getByRole('list', { name: 'My priorities' });
    expect(
      within(priorities)
        .getAllByRole('listitem')
        .map((li) => li.getAttribute('aria-label')),
    ).toEqual(['Fix the login bug', 'Write release notes']);
    expect(screen.getByRole('link', { name: /All 9 in My Tasks/ })).toHaveAttribute('href', '/my-tasks');
    const waiting = screen.getByRole('list', { name: 'Waiting on others' });
    expect(within(waiting).getByText('Vendor contract')).toBeInTheDocument();
    expect(screen.getByText('and 3 more')).toBeInTheDocument();
    const recent = screen.getByRole('list', { name: 'Recent projects' });
    expect(within(recent).getByRole('link', { name: /Website Revamp/ })).toHaveAttribute(
      'href',
      '/projects/p-Website Revamp',
    );
    expect(within(recent).getByText(/2 overdue/)).toBeInTheDocument();
  });

  it('completing a priority checks it off, then it leaves the card (with undo toast)', async () => {
    const { user, completed } = boot({
      priorities: [homeTask('Ship it', -1), homeTask('Then this', 3)],
      counts: { open: 2, due_today: 0, overdue: 1 },
    });
    await user.click(await screen.findByRole('checkbox', { name: 'Complete Ship it' }));
    expect(await screen.findByText('Task completed')).toBeInTheDocument();
    expect(completed).toHaveLength(1);
    await waitFor(() => expect(screen.queryByRole('listitem', { name: 'Ship it' })).toBeNull(), {
      timeout: 3000,
    });
    expect(screen.getByRole('listitem', { name: 'Then this' })).toBeInTheDocument();
  });

  it('empty states: all caught up, and a first-project prompt for brand-new users', async () => {
    boot({ recent_projects: [project('Website Revamp')] });
    expect(await screen.findByText("You're all caught up")).toBeInTheDocument();
    expect(screen.getByText('Nothing overdue')).toBeInTheDocument();
    cleanup();
    server.resetHandlers();
    const { user } = boot({ has_projects: false });
    await user.click(await screen.findByRole('button', { name: 'New project' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('clicking a priority opens the task pane', async () => {
    const { user } = boot({
      priorities: [homeTask('Open me', 1)],
      counts: { open: 1, due_today: 0, overdue: 0 },
    });
    await user.click(await screen.findByRole('button', { name: 'Open me' }));
    await waitFor(() => expect(window.location.search).toContain('task=home-'));
  });

  it('S2.7.3: onboarding checklist shows undone items, and can be dismissed', async () => {
    const { user } = boot(
      { recent_projects: [project('Website Revamp')] },
      { created_project: true, tried_import: false, used_command_palette: false },
    );
    const checklist = await screen.findByRole('list', { name: 'Getting started' });
    expect(within(checklist).getByText('Create a project')).toHaveClass('line-through');
    expect(within(checklist).getByText('Import your existing tasks')).not.toHaveClass('line-through');

    await user.click(screen.getByRole('button', { name: 'Dismiss getting-started checklist' }));
    await waitFor(() =>
      expect(screen.queryByRole('list', { name: 'Getting started' })).not.toBeInTheDocument(),
    );
  });
});
