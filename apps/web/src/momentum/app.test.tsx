import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from './MomentumApp';
import { authHandlers } from './mocks/handlers';
import { notificationHandlers } from './mocks/notifications';
import { projectHandlers } from './mocks/projects';
import { teamHandlers } from './mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

function at(path: string) {
  window.history.replaceState(null, '', path);
}

describe('Momentum app shell', () => {
  it('redirects to dev login, logs in, and lands on Home', async () => {
    server.use(
      ...authHandlers().handlers,
      ...teamHandlers(),
      ...projectHandlers(),
      ...notificationHandlers(),
    );
    at('/');
    render(<MomentumApp />);
    const user = userEvent.setup();

    const pick = await screen.findByRole('button', { name: /Ravi Kumar/ });
    expect(window.location.pathname).toBe('/dev/login');
    await user.click(pick);

    expect(await screen.findByRole('heading', { name: /Ravi$/ })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: /My Tasks/ })).toHaveAttribute('href', '/my-tasks');
  });

  it('opens the command palette with Ctrl+K and navigates', async () => {
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers(),
      ...notificationHandlers(),
    );
    at('/');
    render(<MomentumApp />);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: /Ravi$/ });

    await user.keyboard('{Control>}k{/Control}');
    const input = await screen.findByPlaceholderText(/Search or type a command/);
    await user.type(input, 'Inbox');
    await user.keyboard('{Enter}');
    await waitFor(() => expect(window.location.pathname).toBe('/inbox'));
    expect(await screen.findByRole('heading', { name: 'Inbox' })).toBeInTheDocument();
  });

  it('toggles the Ask Mo panel with Ctrl+J', async () => {
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers(),
      ...notificationHandlers(),
    );
    at('/');
    render(<MomentumApp />);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: /Ravi$/ });
    await user.keyboard('{Control>}j{/Control}');
    expect(await screen.findByRole('complementary', { name: 'Ask Mo' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Mo (AI)' })).toBeInTheDocument();
  });

  it('works when mounted under a base path (embeddable)', async () => {
    const { handlers, requests } = authHandlers({ base: '/x', loggedIn: true });
    server.use(...handlers, ...teamHandlers('/x'), ...projectHandlers('/x'), ...notificationHandlers('/x'));
    at('/x/');
    render(<MomentumApp basePath="/x" />);
    await screen.findByRole('heading', { name: /Ravi$/ });
    expect(requests).toContain('/x/api/v1/config');
    expect(requests).toContain('/x/api/v1/me');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: /Inbox/ })).toHaveAttribute('href', '/x/inbox');
  });
});
