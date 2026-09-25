import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { asanaImportHandlers } from '@/mocks/asanaImport';
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

describe('Asana import (S2.7.1)', () => {
  it('submits the form and shows the resulting counts', async () => {
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers(),
      ...notificationHandlers(),
      ...searchHandlers(),
      ...asanaImportHandlers(),
    );
    window.history.replaceState(null, '', '/settings/import/asana');
    render(<MomentumApp />);
    const user = userEvent.setup();

    await screen.findByRole('heading', { name: 'Import from Asana' });
    await user.type(screen.getByLabelText('Personal Access Token'), '1/abc');
    await user.type(screen.getByLabelText('Asana workspace gid'), 'ws1');
    await user.type(screen.getByLabelText('Asana team gid'), 'team1');
    await user.click(screen.getByRole('button', { name: 'Run import' }));

    expect(await screen.findByText('Import finished')).toBeInTheDocument();
    expect(screen.getByText('teams: 1')).toBeInTheDocument();
    expect(screen.getByText('projects: 2')).toBeInTheDocument();
    expect(screen.getByText('tasks: 5')).toBeInTheDocument();
  });
});
