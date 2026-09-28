import { act, render, screen, waitFor, within } from '@testing-library/react';
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

function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['Existing'] } }),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Recurring tasks (S4.4.2)', () => {
  it('quick-adds a repeating task, shows a plain-English summary in the pane, and can remove it', async () => {
    const user = boot();
    await screen.findByRole('listitem', { name: 'Existing' });
    act(() => (document.activeElement as HTMLElement | null)?.blur());
    await user.keyboard('q');
    const dialog = await screen.findByRole('dialog', { name: 'New task' });
    await user.type(
      within(dialog).getByRole('textbox', { name: 'Task name' }),
      'Water the plants every monday{Enter}',
    );
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'New task' })).toBeNull());

    await user.click(await screen.findByRole('button', { name: 'Open details for Water the plants' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await screen.findByText('Every week on Monday');

    await user.click(within(pane).getByRole('button', { name: 'Remove repeat' }));
    await waitFor(() => expect(within(pane).queryByText('Every week on Monday')).toBeNull());
  });
});
