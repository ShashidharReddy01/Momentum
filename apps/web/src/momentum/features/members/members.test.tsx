import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { membersHandlers } from '@/mocks/members';
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

function boot(role: 'admin' | 'member') {
  server.use(
    ...authHandlers({ loggedIn: true, me: { role } }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...notificationHandlers(),
    ...searchHandlers(),
    ...membersHandlers(),
  );
  window.history.replaceState(null, '', '/settings/members');
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Members (S2.7.3)', () => {
  it('a regular member sees the roster but no invite button', async () => {
    boot('member');
    await screen.findByRole('heading', { name: 'Members' });
    expect(await screen.findByText('Ravi Kumar')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /invite/i })).not.toBeInTheDocument();
  });

  it('an admin invites a member by email and sees it appear as invited', async () => {
    const user = boot('admin');
    await screen.findByRole('heading', { name: 'Members' });

    await user.click(screen.getByRole('button', { name: 'Invite' }));
    const dialog = await screen.findByRole('dialog', { name: 'Invite a member' });
    await user.type(within(dialog).getByLabelText('Email'), 'newperson@acme-demo.test');
    await user.click(within(dialog).getByRole('button', { name: 'Send invite' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const row = await screen.findByText('newperson@acme-demo.test');
    expect(within(row.closest('li')!).getByText('Invited')).toBeInTheDocument();
  });
});
