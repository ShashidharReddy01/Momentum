import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

function boot(path: string, seed: Parameters<typeof projectHandlers>[2]) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, seed),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Share dialog', () => {
  it('admin adds a person and changes their role', async () => {
    const user = boot('/projects/seed-1', [{ name: 'Website Revamp' }]);
    await user.click(await screen.findByRole('button', { name: /Share/ }));
    const dialog = await screen.findByRole('dialog', { name: /Share Website Revamp/ });
    await user.click(within(dialog).getByRole('button', { name: /Add people/ }));
    await user.click(await screen.findByRole('option', { name: /Ana Souza/ }));
    const role = await within(dialog).findByRole('button', { name: 'Role for Ana Souza: Editor' });
    await user.click(role);
    await user.click(await screen.findByRole('menuitem', { name: /Viewer/ }));
    expect(
      await within(dialog).findByRole('button', { name: 'Role for Ana Souza: Viewer' }),
    ).toBeInTheDocument();
  });

  it('viewers see a read-only project and share list', async () => {
    const user = boot('/projects/seed-1', [{ name: 'Mobile App v2', my_role: 'viewer', privacy: 'private' }]);
    expect(await screen.findByText(/You have viewer access/)).toBeInTheDocument();
    // name is not editable
    expect(screen.queryByRole('button', { name: /Project name:/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Project actions' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Share/ }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).queryByRole('button', { name: /Add people/ })).not.toBeInTheDocument();
    expect(within(dialog).getByText('Only invited members')).toBeInTheDocument();
  });
});
