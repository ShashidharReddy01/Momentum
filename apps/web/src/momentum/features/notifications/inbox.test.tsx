import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { notificationHandlers } from '@/mocks/notifications';
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

const NOTE = {
  id: 'note-1',
  kind: 'assigned',
  entity_type: 'task',
  entity_id: 'task-1',
  activity_id: null,
  title: 'You were assigned "First"',
  snippet: null,
  read_at: null,
  archived_at: null,
  created_at: new Date().toISOString(),
};

async function boot(path = '/inbox') {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...notificationHandlers('', [{ ...NOTE }]),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Inbox (S2.5.2)', () => {
  it('the bell shows the unread count', async () => {
    await boot('/');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Notifications \(1 unread\)/ })).toBeInTheDocument(),
    );
  });

  it('lists a notification, opens the task pane on click, and marks it read', async () => {
    const user = await boot();
    await screen.findByText('You were assigned "First"');
    await user.click(screen.getByRole('button', { name: 'You were assigned "First"' }));

    await waitFor(() =>
      expect(screen.getByRole('complementary', { name: 'Task details' })).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Notifications \(1 unread\)/ })).not.toBeInTheDocument(),
    );
  });

  it('archiving moves a notification to the Archive tab', async () => {
    const user = await boot();
    await screen.findByText('You were assigned "First"');
    await user.click(screen.getByRole('button', { name: 'Archive' }));
    await waitFor(() => expect(screen.queryByText('You were assigned "First"')).toBeNull());

    await user.click(screen.getByRole('tab', { name: 'Archive' }));
    await waitFor(() => expect(screen.getByText('You were assigned "First"')).toBeInTheDocument());
  });
});
