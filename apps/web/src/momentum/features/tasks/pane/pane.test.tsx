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

async function boot(path = '/projects/seed-1') {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'Done'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First', 'Second', 'Third'] } }),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return userEvent.setup();
}

const row = (name: string) => screen.getByRole('listitem', { name });
const pane = () => screen.getByRole('complementary', { name: 'Task details' });
const paneTitle = () => within(pane()).getByRole('textbox', { name: 'Task name' });

describe('Task pane', () => {
  it('opens from a row click, shows the task, and closes with Esc and the close button', async () => {
    const user = await boot();
    await user.click(await screen.findByRole('button', { name: 'Open details for Second' }));
    await waitFor(() => expect(paneTitle()).toHaveValue('Second'));
    expect(window.location.search).toContain('task=');
    expect(row('Second')).toHaveAttribute('data-open');
    expect(within(pane()).getByText('Website Revamp')).toBeInTheDocument();
    act(() => pane().focus());
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull();
    expect(window.location.search).not.toContain('task=');
    // Space on a focused row toggles it
    act(() => row('First').focus());
    await user.keyboard(' ');
    await waitFor(() => expect(paneTitle()).toHaveValue('First'));
    await user.click(within(pane()).getByRole('button', { name: 'Close details' }));
    expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull();
  });

  it('J/K step through the list while the pane stays open; list arrows move the pane too', async () => {
    const user = await boot();
    await user.click(await screen.findByRole('button', { name: 'Open details for First' }));
    await waitFor(() => expect(paneTitle()).toHaveValue('First'));
    act(() => pane().focus());
    await user.keyboard('j');
    await waitFor(() => expect(paneTitle()).toHaveValue('Second'));
    await user.keyboard('j');
    await waitFor(() => expect(paneTitle()).toHaveValue('Third'));
    await user.keyboard('j'); // stays at the end
    await user.keyboard('k');
    await waitFor(() => expect(paneTitle()).toHaveValue('Second'));
    act(() => row('Second').focus());
    await user.keyboard('{ArrowUp}');
    await waitFor(() => expect(paneTitle()).toHaveValue('First'));
  });

  it('edits in the pane show in the list (title, assignee), and the list edits show in the pane', async () => {
    const user = await boot();
    await user.click(await screen.findByRole('button', { name: 'Open details for First' }));
    await waitFor(() => expect(paneTitle()).toHaveValue('First'));
    await user.clear(paneTitle());
    await user.type(paneTitle(), 'First, renamed{Enter}');
    expect(await screen.findByRole('listitem', { name: 'First, renamed' })).toBeInTheDocument();
    await user.click(within(pane()).getByRole('button', { name: 'Assign' }));
    await user.type(await screen.findByPlaceholderText('Assign to…'), 'ana{Enter}');
    await waitFor(() =>
      expect(
        within(row('First, renamed')).getByRole('button', { name: /Assignee: Ana/ }),
      ).toBeInTheDocument(),
    );
    // and back: assign from the list, the pane follows
    act(() => row('First, renamed').focus());
    await user.keyboard('m');
    await waitFor(() =>
      expect(within(pane()).getByRole('button', { name: /Assignee: Ravi/ })).toBeInTheDocument(),
    );
  });

  it('delete from the pane closes it and removes the row (with undo)', async () => {
    const user = await boot();
    await user.click(await screen.findByRole('button', { name: 'Open details for Third' }));
    await waitFor(() => expect(paneTitle()).toHaveValue('Third'));
    await user.click(within(pane()).getByRole('button', { name: 'More actions' }));
    await user.click(await screen.findByRole('menuitem', { name: /Delete task/ }));
    expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull();
    expect(screen.queryByRole('listitem', { name: 'Third' })).toBeNull();
    expect(await screen.findByText('Task deleted')).toBeInTheDocument();
  });

  it('a missing task says so instead of failing', async () => {
    await boot('/projects/seed-1?task=gone');
    expect(await screen.findByText(/deleted, or you don't have access/)).toBeInTheDocument();
  });

  it('the full-page route shows the task', async () => {
    await boot('/task/task-2');
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Task name' })).toHaveValue('Second'));
    expect(screen.getByRole('region', { name: 'Description' })).toBeInTheDocument();
  });
});
