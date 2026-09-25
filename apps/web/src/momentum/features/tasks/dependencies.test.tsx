import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { dependencyHandlers } from '@/mocks/dependencies';
import { multiHomingHandlers } from '@/mocks/multiHoming';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
  vi.restoreAllMocks();
});
afterAll(() => server.close());

async function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', color: null, my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    // Registered before taskHandlers so its /complete override (needed for the
    // has_incomplete_blockers confirm flow) wins — MSW matches handlers in registration order.
    ...dependencyHandlers('', [
      { id: 'task-1', title: 'First', completed_at: null },
      { id: 'task-2', title: 'Second', completed_at: null },
    ]),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First', 'Second'] } }),
    ...multiHomingHandlers(
      '',
      [{ id: 'seed-1', name: 'Website Revamp', color: null }],
      [
        { task_id: 'task-1', project_id: 'seed-1', section_id: 'sec-1', position: '100000' },
        { task_id: 'task-2', project_id: 'seed-1', section_id: 'sec-1', position: '200000' },
      ],
    ),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Open details for First' });
  return user;
}

describe('Dependencies (S2.4.2)', () => {
  it('adds a blocker from the pane and shows it in both directions', async () => {
    const user = await boot();
    await user.click(await screen.findByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });

    await user.click(within(pane).getByRole('button', { name: 'Add a dependency' }));
    await user.type(screen.getByPlaceholderText('Search tasks in this project…'), 'Second');
    await user.click(await screen.findByRole('option', { name: 'Second' }));
    await waitFor(() => expect(within(pane).getByText('Second')).toBeInTheDocument());

    // the "waiting on" icon shows on First's row
    const row = screen.getByRole('listitem', { name: 'First' });
    await waitFor(() => expect(within(row).getByTitle('Waiting on another task')).toBeInTheDocument());

    // Second's own pane shows it's blocking First
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: 'Open details for Second' }));
    const pane2 = await screen.findByRole('complementary', { name: 'Task details' });
    await waitFor(() => expect(within(pane2).getByText('Blocking')).toBeInTheDocument());
    expect(within(pane2).getByText('First')).toBeInTheDocument();
  });

  it('completing a blocked task asks for confirmation, and force-completes on yes', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = await boot();
    await user.click(await screen.findByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await user.click(within(pane).getByRole('button', { name: 'Add a dependency' }));
    await user.type(screen.getByPlaceholderText('Search tasks in this project…'), 'Second');
    await user.click(await screen.findByRole('option', { name: 'Second' }));
    await waitFor(() => expect(within(pane).getByText('Second')).toBeInTheDocument());

    await user.click(within(pane).getByRole('button', { name: /Mark complete/ }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    await waitFor(() => expect(within(pane).getByRole('button', { name: /Completed/ })).toBeInTheDocument());
  });

  it('removing a blocker detaches it', async () => {
    const user = await boot();
    await user.click(await screen.findByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await user.click(within(pane).getByRole('button', { name: 'Add a dependency' }));
    await user.type(screen.getByPlaceholderText('Search tasks in this project…'), 'Second');
    await user.click(await screen.findByRole('option', { name: 'Second' }));
    await waitFor(() => expect(within(pane).getByText('Second')).toBeInTheDocument());

    await user.click(within(pane).getByRole('button', { name: 'Remove dependency: Second' }));
    await waitFor(() => expect(within(pane).queryByText('Second')).toBeNull());
  });
});
