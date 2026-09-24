import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { tagHandlers } from '@/mocks/tags';
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
    ...tagHandlers(),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Open details for First' });
  return user;
}

describe('Tags (S2.3.3)', () => {
  it('tags a task from the pane by creating a new tag inline', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });

    await user.click(within(pane).getByRole('button', { name: 'Add tag' }));
    await user.type(screen.getByPlaceholderText('Search or create a tag…'), 'Urgent');
    await user.click(await screen.findByRole('option', { name: /Create "Urgent"/ }));

    await waitFor(() => expect(within(pane).getByText('Urgent')).toBeInTheDocument());
  });

  it('a tag on a task shows as a chip on the list row', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await user.click(within(pane).getByRole('button', { name: 'Add tag' }));
    await user.type(screen.getByPlaceholderText('Search or create a tag…'), 'Urgent');
    await user.click(await screen.findByRole('option', { name: /Create "Urgent"/ }));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull());

    const row = screen.getByRole('listitem', { name: 'First' });
    await waitFor(() => expect(within(row).getByText('Urgent')).toBeInTheDocument());
  });

  it('removing a tag from the pane detaches it', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await user.click(within(pane).getByRole('button', { name: 'Add tag' }));
    await user.type(screen.getByPlaceholderText('Search or create a tag…'), 'Urgent');
    await user.click(await screen.findByRole('option', { name: /Create "Urgent"/ }));
    await waitFor(() => expect(within(pane).getByText('Urgent')).toBeInTheDocument());

    await user.click(within(pane).getByRole('button', { name: 'Remove tag: Urgent' }));
    await waitFor(() => expect(within(pane).queryByText('Urgent')).toBeNull());
  });

  it('the tag page lists tasks with that tag and opens the pane on click', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await user.click(within(pane).getByRole('button', { name: 'Add tag' }));
    await user.type(screen.getByPlaceholderText('Search or create a tag…'), 'Urgent');
    await user.click(await screen.findByRole('option', { name: /Create "Urgent"/ }));
    const tagLink = await within(pane).findByRole('link', { name: 'Urgent' });
    await user.click(tagLink);

    await screen.findByRole('button', { name: /^Tag name: Urgent/ });
    const list = await screen.findByRole('list', { name: 'Tagged tasks' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(1);

    await user.click(within(rows[0]!).getByText('Task'));
    await waitFor(() =>
      expect(screen.getByRole('complementary', { name: 'Task details' })).toBeInTheDocument(),
    );
  });
});
