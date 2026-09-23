import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { homeHandlers } from '@/mocks/home';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});
afterAll(() => server.close());

function narrowScreen() {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: q.includes('max-width'),
    media: q,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

describe('Narrow screens', () => {
  it('the sidebar is a drawer: opens from the top bar, closes on navigation, Escape or backdrop', async () => {
    narrowScreen();
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...homeHandlers().handlers,
      ...teamHandlers(),
      ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
      ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
      ...taskHandlers(),
    );
    window.history.replaceState(null, '', '/');
    render(<MomentumApp />);
    const user = userEvent.setup();
    const menu = await screen.findByRole('button', { name: 'Open menu' });
    expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull(); // hidden
    await user.click(menu);
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeVisible();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull());
    await user.click(menu);
    await user.click(screen.getByRole('button', { name: 'Close menu' }));
    expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull();
    await user.click(menu);
    await user.click(await screen.findByRole('link', { name: 'My Tasks' }));
    await waitFor(() => expect(window.location.pathname).toBe('/my-tasks'));
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull());
  });
});
