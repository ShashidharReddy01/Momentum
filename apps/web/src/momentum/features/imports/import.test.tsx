import { render, screen, within } from '@testing-library/react';
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

describe('Asana import wizard (S7.4.2)', () => {
  it('connects, picks a team and projects, dry-runs, then imports in steps with the token each time', async () => {
    const asana = asanaImportHandlers();
    server.use(
      ...authHandlers({ loggedIn: true }).handlers,
      ...teamHandlers(),
      ...projectHandlers(),
      ...notificationHandlers(),
      ...searchHandlers(),
      ...asana,
    );
    window.history.replaceState(null, '', '/settings/import/asana');
    render(<MomentumApp />);
    const user = userEvent.setup();

    await screen.findByRole('heading', { name: 'Import from Asana' });
    await user.type(screen.getByLabelText('Personal Access Token'), '1/abc');
    await user.click(screen.getByRole('button', { name: 'Connect' }));
    // one workspace: chosen for you; then the team
    await user.selectOptions(await screen.findByLabelText('Asana team'), 'team1');
    const projects = await screen.findByRole('group', { name: /Projects \(2 of 2\)/ });
    expect(within(projects).getByText('archived')).toBeInTheDocument();
    await user.click(within(projects).getByRole('checkbox', { name: /Old site/ }));
    expect(screen.getByLabelText('Team name in Momentum')).toHaveValue('Product');

    await user.click(screen.getByRole('button', { name: 'Dry run' }));
    expect(await screen.findByText('Dry run finished: nothing was changed')).toBeInTheDocument();
    const would = screen.getByLabelText('Would import');
    expect(within(would).getByText('Tasks').nextSibling).toHaveTextContent('5');
    expect(screen.getByText(/formula fields imported as a text snapshot/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Import' }));
    expect(await screen.findByText('Import finished')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Imported')).getByText('Comments').nextSibling).toHaveTextContent(
      '3',
    );
    await user.click(screen.getByText('1 not imported'));
    expect(screen.getByText('task t3: a legacy section row, not a task')).toBeInTheDocument();
    // two steps per run, the token sent with every one
    expect(asana.steps).toHaveLength(4);
    expect(asana.steps.every((s) => s.pat === '1/abc')).toBe(true);
  });
});
