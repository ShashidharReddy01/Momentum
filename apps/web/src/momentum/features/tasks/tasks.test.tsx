import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

function boot(tasks: string[] = ['Existing A', 'Existing B'], role = 'admin') {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: role }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'Done'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': tasks } }),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  return userEvent.setup();
}

const titles = (section: string) =>
  within(screen.getByRole('list', { name: `Tasks in ${section}` }))
    .queryAllByRole('listitem')
    .map((li) => li.getAttribute('aria-label'))
    .filter((x) => x !== 'New task');

describe('Task list', () => {
  it('creates 10 tasks rapidly with Enter, in order, keeping focus', async () => {
    const user = boot();
    await screen.findByRole('listitem', { name: 'Existing B' });
    const backlog = screen.getByRole('list', { name: 'Tasks in Backlog' });
    await user.click(within(backlog).getByRole('button', { name: /Add task/ }));
    for (let i = 1; i <= 10; i++) {
      const input = screen.getByRole('textbox', { name: 'New task name' });
      expect(input).toHaveFocus();
      await user.type(input, `Task ${i}{Enter}`);
    }
    await user.keyboard('{Escape}');
    const expected = ['Existing A', 'Existing B', ...Array.from({ length: 10 }, (_, i) => `Task ${i + 1}`)];
    expect(titles('Backlog')).toEqual(expected);
    // server order matches after refetch (temp ids resolved in order)
    await waitFor(() => expect(within(backlog).queryAllByText('…')).toHaveLength(0));
  });

  it('Enter on an existing task opens a new row right below it', async () => {
    const user = boot();
    await user.click(await screen.findByRole('button', { name: 'Existing A' }));
    const input = screen.getByRole('textbox', { name: 'Task name' });
    await user.type(input, ' edited{Enter}');
    await user.type(screen.getByRole('textbox', { name: 'New task name' }), 'Between{Enter}{Escape}');
    expect(titles('Backlog')).toEqual(['Existing A edited', 'Between', 'Existing B']);
  });

  it('completes a task with fade, and Show completed brings it back in place', async () => {
    const user = boot(['One', 'Two', 'Three']);
    await user.click(await screen.findByRole('checkbox', { name: 'Complete Two' }));
    expect(await screen.findByText('Task completed')).toBeInTheDocument();
    await waitFor(() => expect(titles('Backlog')).toEqual(['One', 'Three']), { timeout: 3000 });
    await user.click(screen.getByRole('button', { name: /Show completed/ }));
    await waitFor(() => expect(titles('Backlog')).toEqual(['One', 'Two', 'Three']));
    expect(screen.getByRole('checkbox', { name: 'Mark Two incomplete' })).toBeChecked();
  });

  it('pasting several lines creates them as a batch', async () => {
    const user = boot([]);
    const backlog = await screen.findByRole('list', { name: 'Tasks in Backlog' });
    await user.click(within(backlog).getByRole('button', { name: /Add task/ }));
    const input = screen.getByRole('textbox', { name: 'New task name' });
    act(() => {
      fireEvent.paste(input, { clipboardData: { getData: () => 'alpha\nbeta\n\ngamma' } });
    });
    expect(await screen.findByText('3 tasks added')).toBeInTheDocument();
    await waitFor(() => expect(titles('Backlog')).toEqual(['alpha', 'beta', 'gamma']));
  });

  it('viewers see tasks but cannot edit or complete them', async () => {
    boot(['Read only'], 'viewer');
    const check = await screen.findByRole('checkbox', { name: 'Complete Read only' });
    expect(check).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Add task/ })).not.toBeInTheDocument();
  });
});
