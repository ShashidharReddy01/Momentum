import { render, screen, waitFor, within } from '@testing-library/react';
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

async function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Open details for First' });
  return user;
}

describe('Approvals (S4.4.1)', () => {
  it('converts a task to an approval, shows a pending banner, and approving completes it', async () => {
    const user = await boot();
    await user.click(await screen.findByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });

    await user.click(within(pane).getByRole('button', { name: 'More actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Convert to approval' }));

    await screen.findByText('Pending approval');
    const approve = within(pane).getByRole('button', { name: 'Approve' });
    await user.click(approve);

    await screen.findByText('Approved');
    await waitFor(() => expect(within(pane).getByRole('button', { name: /Completed/ })).toBeInTheDocument());
  });
});
