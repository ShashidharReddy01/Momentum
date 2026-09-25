import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
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
});
afterAll(() => server.close());

const HOME = { id: 'seed-1', name: 'Website Revamp', color: 'proj-6' };
const OTHER = { id: 'seed-2', name: 'Mobile App v2', color: 'proj-8' };

async function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [
      { name: HOME.name, color: HOME.color, my_role: 'admin' },
      { name: OTHER.name, color: OTHER.color, my_role: 'admin' },
    ]),
    ...sectionHandlers('', { [HOME.id]: ['Backlog'], [OTHER.id]: ['To do'] }),
    ...taskHandlers('', { [HOME.id]: { 'sec-1': ['First'] } }),
    ...multiHomingHandlers(
      '',
      [HOME, OTHER],
      [{ task_id: 'task-1', project_id: HOME.id, section_id: 'sec-1', position: '100000' }],
    ),
  );
  window.history.replaceState(null, '', `/projects/${HOME.id}`);
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Open details for First' });
  return user;
}

describe('Multi-homing (S2.4.1)', () => {
  it('the pane shows the current project and lets you add another', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await waitFor(() => expect(within(pane).getByText(HOME.name)).toBeInTheDocument());

    await user.click(within(pane).getByRole('button', { name: 'Add to another project' }));
    await user.click(await screen.findByRole('option', { name: OTHER.name }));
    await waitFor(() => expect(within(pane).getByText(OTHER.name)).toBeInTheDocument());
  });

  it('a task added to a second project shows an "also in" chip on the list row', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await user.click(within(pane).getByRole('button', { name: 'Add to another project' }));
    await user.click(await screen.findByRole('option', { name: OTHER.name }));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull());

    const row = screen.getByRole('listitem', { name: 'First' });
    await waitFor(() => expect(within(row).getByTitle(`Also in ${OTHER.name}`)).toBeInTheDocument());
  });

  it('removing a project chip detaches the placement', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await user.click(within(pane).getByRole('button', { name: 'Add to another project' }));
    await user.click(await screen.findByRole('option', { name: OTHER.name }));
    await waitFor(() => expect(within(pane).getByText(OTHER.name)).toBeInTheDocument());

    await user.click(within(pane).getByRole('button', { name: `Remove from ${OTHER.name}` }));
    await waitFor(() => expect(within(pane).queryByText(OTHER.name)).toBeNull());
  });
});
