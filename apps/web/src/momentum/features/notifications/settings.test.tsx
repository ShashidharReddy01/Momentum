import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { notificationHandlers } from '@/mocks/notifications';
import { onboardingHandlers } from '@/mocks/onboarding';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

async function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...notificationHandlers(),
  );
  window.history.replaceState(null, '', '/settings/notifications');
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Notification settings (S2.5.3)', () => {
  it('reaches the page from the user menu, changes a channel, and saves the digest time', async () => {
    await boot();
    await screen.findByRole('heading', { name: 'Notification settings' });

    const assignedSelect = await screen.findByLabelText('Assigned to me channel');
    expect(assignedSelect).toHaveValue('in_app');
    await userEvent.setup().selectOptions(assignedSelect, 'off');
    await waitFor(() => expect(assignedSelect).toHaveValue('off'));

    const digest = screen.getByLabelText('Daily digest time');
    await userEvent.setup().type(digest, '0900');
    await waitFor(() => expect(digest).toHaveValue('09:00'));
  });

  it('the sidebar user menu links to the settings page', async () => {
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers(),
      ...notificationHandlers(),
      ...onboardingHandlers(),
    );
    window.history.replaceState(null, '', '/');
    render(<MomentumApp />);
    const user = userEvent.setup();
    await screen.findByRole('heading', { name: /Ravi$/ });

    await user.click(screen.getByRole('button', { name: 'Account menu' }));
    await user.click(await screen.findByText('Notification settings'));
    await waitFor(() => expect(window.location.pathname).toBe('/settings/notifications'));
  });
});
