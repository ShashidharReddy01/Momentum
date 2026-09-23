import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { homeHandlers } from '@/mocks/home';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { lastCreated, taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  lastCreated.length = 0;
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

const ME = '01a0ccaf-8f68-77d2-a888-584ea1e80ea8';

function boot(
  path: string,
  projects = [
    { name: 'Website Revamp', my_role: 'admin' },
    { name: 'Aardvark', my_role: 'admin' }, // sorts first: the default must come from the page
  ],
) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...homeHandlers().handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, projects),
    ...sectionHandlers('', { 'seed-1': ['Backlog'], 'seed-2': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['Existing'] } }),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Quick add', () => {
  it('Q on a project page adds a task there, assigned to me by default, with undo', async () => {
    const user = boot('/projects/seed-1');
    await screen.findByRole('listitem', { name: 'Existing' });
    act(() => (document.activeElement as HTMLElement | null)?.blur());
    await user.keyboard('q');
    const dialog = await screen.findByRole('dialog', { name: 'New task' });
    expect(within(dialog).getByLabelText('Project')).toHaveValue('seed-1');
    expect(within(dialog).getByRole('button', { name: 'Assignee: Me' })).toBeInTheDocument();
    await user.type(within(dialog).getByRole('textbox', { name: 'Task name' }), 'Call the printer{Enter}');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'New task' })).toBeNull());
    expect(lastCreated[0]).toMatchObject({ title: 'Call the printer', assignee_id: ME, due_on: null });
    expect(await screen.findByText('Task added to Website Revamp')).toBeInTheDocument();
    expect(await screen.findByRole('listitem', { name: 'Call the printer' })).toBeInTheDocument();
  });

  it('from the Create menu: can unassign and set a due date; empty names are not sent', async () => {
    const user = boot('/');
    await user.click(await screen.findByRole('button', { name: 'Create' }));
    await user.click(await screen.findByRole('menuitem', { name: /Task/ }));
    const dialog = await screen.findByRole('dialog', { name: 'New task' });
    expect(within(dialog).getByRole('button', { name: 'Add task' })).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: 'Assignee: Me' }));
    await user.click(await screen.findByRole('option', { name: /Unassign/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Set due date' }));
    const date = await screen.findByRole('textbox', { name: 'Due date' });
    await user.type(date, '2031-03-04{Enter}');
    await user.type(within(dialog).getByRole('textbox', { name: 'Task name' }), '   ');
    expect(within(dialog).getByRole('button', { name: 'Add task' })).toBeDisabled();
    await user.type(within(dialog).getByRole('textbox', { name: 'Task name' }), 'Book venue');
    await user.click(within(dialog).getByRole('button', { name: 'Add task' }));
    await waitFor(() => expect(lastCreated).toHaveLength(1));
    expect(lastCreated[0]).toMatchObject({ title: 'Book venue', assignee_id: null, due_on: '2031-03-04' });
  });

  it('explains when there is no project I can add to', async () => {
    const user = boot('/', [{ name: 'Read only', my_role: 'viewer' }]);
    await screen.findByRole('heading', { level: 1 });
    await user.keyboard('q');
    expect(await screen.findByText(/once you're an editor in a project/)).toBeInTheDocument();
  });
});
