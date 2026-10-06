import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { ravi } from '@/mocks/fixtures';
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

const ana = {
  id: 'u-ana',
  email: 'ana@acme-demo.test',
  name: 'Ana Souza',
  avatar_url: null,
  role: 'member',
  status: 'active',
  is_agent: false,
  timezone: 'UTC',
};

function boot(role: 'admin' | 'member') {
  server.use(
    ...authHandlers({ loggedIn: true, me: { role } }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...notificationHandlers(),
    ...searchHandlers(),
    ...membersHandlers('', [ravi, ana]),
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

  it('an admin changes a role, disables someone and hands their work on (S7.5.4)', async () => {
    const user = boot('admin');
    const row = await screen.findByRole('listitem', { name: 'Ana Souza' });
    expect(
      within(screen.getByRole('listitem', { name: 'Ravi Kumar' })).queryByLabelText(/Role for/),
    ).toBeNull();

    await user.selectOptions(within(row).getByLabelText('Role for Ana Souza'), 'admin');
    expect(await screen.findByText('Ana Souza is now an admin')).toBeInTheDocument();

    await user.click(within(row).getByRole('button', { name: 'More for Ana Souza' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Disable' }));
    await waitFor(() => expect(within(row).getByText('Disabled')).toBeInTheDocument());

    await user.click(within(row).getByRole('button', { name: 'More for Ana Souza' }));
    await user.click(await screen.findByRole('menuitem', { name: /Hand on their work/ }));
    const dialog = await screen.findByRole('dialog', { name: /Hand on Ana Souza/ });
    await user.selectOptions(within(dialog).getByLabelText('Give it to'), 'Ravi Kumar');
    await user.click(within(dialog).getByRole('button', { name: 'Hand on' }));
    expect(
      await screen.findByText(/4 open tasks and 1 project handed to Ravi Kumar; 2 in private projects/),
    ).toBeInTheDocument();
  });
});
