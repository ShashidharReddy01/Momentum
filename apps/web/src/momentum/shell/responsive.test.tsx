import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { homeHandlers } from '@/mocks/home';
import { onboardingHandlers } from '@/mocks/onboarding';
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
      ...onboardingHandlers(),
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

function compactScreen() {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: q.includes('1279'),
    media: q,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

describe('The rail (UX2)', () => {
  function boot() {
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...homeHandlers().handlers,
      ...teamHandlers(),
      ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
      ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
      ...taskHandlers(),
      ...onboardingHandlers(),
    );
    window.history.replaceState(null, '', '/');
    render(<MomentumApp />);
  }

  it('below 1280px starts as icons with named links, and the top-bar toggle expands it', async () => {
    compactScreen();
    boot();
    const user = userEvent.setup();
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    await waitFor(() => expect(nav).toHaveAttribute('data-icons-only'));
    expect(screen.getByRole('link', { name: 'My Tasks' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Create' })).toBeVisible();
    expect(await screen.findByRole('button', { name: 'Account menu' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Toggle sidebar' }));
    expect(nav).not.toHaveAttribute('data-icons-only');
    expect(screen.getByText('Momentum')).toBeVisible();
  });

  it('on wide windows the toggle collapses to icons and remembers it', async () => {
    boot();
    const user = userEvent.setup();
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    expect(nav).not.toHaveAttribute('data-icons-only');
    await user.click(await screen.findByRole('button', { name: 'Toggle sidebar' }));
    expect(nav).toHaveAttribute('data-icons-only');
    expect(window.localStorage.getItem('momentum.ui')).toContain('"sidebarCollapsed":true');
  });
});
