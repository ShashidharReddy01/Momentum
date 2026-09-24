import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

function boot(seed: Record<string, unknown> = {}) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin', ...seed }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': [] } }),
  );
}

const currentTab = () => screen.getByRole('link', { current: 'page' });

describe('View switcher and defaults (S2.2.3)', () => {
  it("a bare project URL redirects to the project's default view", async () => {
    boot({ default_view: 'board' });
    window.history.replaceState(null, '', '/projects/seed-1');
    render(<MomentumApp />);
    await waitFor(() => expect(currentTab()).toHaveTextContent('Board'));
    expect(window.location.pathname).toBe('/projects/seed-1/board');
  });

  it('a project defaulting to list needs no redirect', async () => {
    boot({ default_view: 'list' });
    window.history.replaceState(null, '', '/projects/seed-1');
    render(<MomentumApp />);
    await screen.findByRole('list', { name: 'Tasks in Backlog' }); // list view rendered
    expect(window.location.pathname).toBe('/projects/seed-1');
    expect(currentTab()).toHaveTextContent('List');
  });

  it("an explicitly visited view is remembered over the project's default on the next visit", async () => {
    boot({ default_view: 'list' });
    window.history.replaceState(null, '', '/projects/seed-1/calendar');
    const { unmount } = render(<MomentumApp />);
    await screen.findAllByRole('gridcell');
    expect(currentTab()).toHaveTextContent('Calendar');
    await new Promise((r) => setTimeout(r, 0)); // let the (unawaited) save land
    unmount();

    window.history.replaceState(null, '', '/projects/seed-1');
    render(<MomentumApp />);
    await waitFor(() => expect(currentTab()).toHaveTextContent('Calendar'));
    expect(window.location.pathname).toBe('/projects/seed-1/calendar');
  });

  it('an admin can change the default view from the project menu', async () => {
    boot({ default_view: 'list' });
    window.history.replaceState(null, '', '/projects/seed-1/board');
    render(<MomentumApp />);
    const user = userEvent.setup();
    await screen.findByRole('region', { name: 'Column Backlog' });

    await user.click(screen.getByRole('button', { name: 'Project actions' }));
    const calendarOption = screen.getByRole('menuitemradio', { name: 'Calendar' });
    expect(calendarOption).toHaveAttribute('aria-checked', 'false');
    await user.click(calendarOption);

    await user.click(screen.getByRole('button', { name: 'Project actions' }));
    await waitFor(() =>
      expect(screen.getByRole('menuitemradio', { name: 'Calendar' })).toHaveAttribute('aria-checked', 'true'),
    );
  });

  it('a non-admin sees no "Project actions" menu (so no default-view control)', async () => {
    boot({ default_view: 'list', my_role: 'editor' });
    window.history.replaceState(null, '', '/projects/seed-1');
    render(<MomentumApp />);
    await screen.findByRole('list', { name: 'Tasks in Backlog' });
    expect(screen.queryByRole('button', { name: 'Project actions' })).toBeNull();
  });
});
