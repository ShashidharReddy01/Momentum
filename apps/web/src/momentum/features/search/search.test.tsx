import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { searchHandlers } from '@/mocks/search';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

const RESULTS = {
  onboarding: {
    tasks: [
      {
        id: 'task-9',
        title: 'Redesign the onboarding flow',
        type: 'task',
        completed_at: null,
        project_id: 'seed-1',
        project_name: 'Website Revamp',
      },
    ],
    projects: [],
    people: [],
    comments: [],
  },
};

function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...notificationHandlers(),
    ...searchHandlers('', RESULTS),
  );
  window.history.replaceState(null, '', '/');
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Global search (S2.6.2)', () => {
  it('shows quick results in the command palette and navigates on click', async () => {
    const user = await boot();
    await screen.findByRole('heading', { name: /Ravi$/ });

    await user.keyboard('{Control>}k{/Control}');
    const input = await screen.findByPlaceholderText(/Search or type a command/);
    await user.type(input, 'onboarding');

    const hit = await screen.findByText('Redesign the onboarding flow');
    await user.click(hit);

    await waitFor(() => expect(window.location.pathname).toBe('/task/task-9'));
  });

  it('the search results page filters by type', async () => {
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
      ...notificationHandlers(),
      ...searchHandlers('', RESULTS),
    );
    window.history.replaceState(null, '', '/search?q=onboarding');
    render(<MomentumApp />);
    const user = userEvent.setup();

    await screen.findByText('Redesign the onboarding flow');

    await user.click(screen.getByRole('button', { name: 'Tasks' }));
    await waitFor(() => expect(screen.queryByText('Redesign the onboarding flow')).not.toBeInTheDocument());
  });
});
