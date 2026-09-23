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

async function boot(backlog = ['One', 'Two', 'Three', 'Four'], done: string[] = ['Shipped']) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'Done'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': backlog, 'sec-2': done } }),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('listitem', { name: backlog.at(-1) });
  return user;
}

const row = (name: string) => screen.getByRole('listitem', { name });
const titles = (section: string) =>
  within(screen.getByRole('list', { name: `Tasks in ${section}` }))
    .queryAllByRole('listitem')
    .map((li) => li.getAttribute('aria-label'));
const selectedTitles = () =>
  screen
    .queryAllByRole('listitem')
    .filter((li) => li.hasAttribute('data-selected'))
    .map((li) => li.getAttribute('aria-label'));

describe('List selection and keyboard', () => {
  it('arrows and J/K move focus across sections; Shift+arrows select a range; Esc clears', async () => {
    const user = await boot();
    act(() => row('One').focus());
    await user.keyboard('{ArrowDown}');
    expect(row('Two')).toHaveFocus();
    await user.keyboard('jjj');
    expect(row('Shipped')).toHaveFocus(); // crossed into the next section
    await user.keyboard('j');
    expect(row('Shipped')).toHaveFocus(); // stays at the end
    await user.keyboard('kk');
    expect(row('Three')).toHaveFocus();
    await user.keyboard('{Shift>}{ArrowUp}{ArrowUp}{/Shift}');
    expect(selectedTitles()).toEqual(['One', 'Two', 'Three']);
    expect(screen.getByRole('toolbar', { name: '3 tasks selected' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(selectedTitles()).toEqual([]);
    expect(screen.queryByRole('toolbar', { name: /tasks selected/ })).toBeNull();
  });

  it('⌘-click toggles, Shift-click selects a range, a plain click resets', async () => {
    const user = await boot();
    await user.click(row('One'));
    await user.keyboard('{Meta>}');
    await user.click(row('Three'));
    await user.keyboard('{/Meta}');
    expect(selectedTitles()).toEqual(['One', 'Three']);
    await user.keyboard('{Shift>}');
    await user.click(row('Shipped'));
    await user.keyboard('{/Shift}');
    expect(selectedTitles()).toEqual(['Three', 'Four', 'Shipped']);
    await user.click(row('Two'));
    expect(selectedTitles()).toEqual([]);
    // modifier clicks never start editing the title
    expect(
      within(screen.getByRole('list', { name: 'Tasks in Backlog' })).queryByRole('textbox', {
        name: 'Task name',
      }),
    ).toBeNull();
  });

  it('⌘A selects the focused section; bulk assign applies to all with one toast', async () => {
    const user = await boot();
    act(() => row('Two').focus());
    await user.keyboard('{Meta>}a{/Meta}');
    expect(selectedTitles()).toEqual(['One', 'Two', 'Three', 'Four']);
    await user.keyboard('a'); // opens the bulk assignee picker
    await user.type(await screen.findByPlaceholderText('Assign to…'), 'ana{Enter}');
    expect(await screen.findByText('4 tasks assigned to Ana Souza')).toBeInTheDocument();
    for (const t of ['One', 'Two', 'Three', 'Four'])
      expect(within(row(t)).getByRole('button', { name: /Assignee: Ana/ })).toBeInTheDocument();
    expect(within(row('Shipped')).getByRole('button', { name: 'Assign' })).toBeInTheDocument();
  });

  it('⌘↓ / ⌘↑ move the focused task, crossing section edges', async () => {
    const user = await boot();
    act(() => row('One').focus());
    await user.keyboard('{Meta>}{ArrowDown}{/Meta}');
    expect(titles('Backlog')).toEqual(['Two', 'One', 'Three', 'Four']);
    act(() => row('Four').focus());
    await user.keyboard('{Meta>}{ArrowDown}{/Meta}');
    await waitFor(() => expect(titles('Done')).toEqual(['Four', 'Shipped']));
    expect(await screen.findByText('Moved to Done')).toBeInTheDocument();
    await user.keyboard('{Meta>}{ArrowUp}{/Meta}');
    await waitFor(() => expect(titles('Backlog')).toEqual(['Two', 'One', 'Three', 'Four']));
  });

  it('bulk move to a section keeps the relative order and appends', async () => {
    const user = await boot();
    await user.click(row('Three'));
    await user.keyboard('{Meta>}');
    await user.click(row('One'));
    await user.keyboard('{/Meta}');
    await user.click(screen.getByRole('button', { name: /Move/ }));
    await user.click(await screen.findByRole('menuitem', { name: 'Done' }));
    await waitFor(() => expect(titles('Done')).toEqual(['Shipped', 'One', 'Three']));
    expect(titles('Backlog')).toEqual(['Two', 'Four']);
    expect(await screen.findByText('Moved 2 tasks to Done')).toBeInTheDocument();
  });

  it('⌘Enter completes the selection; ⌘⌫ deletes it', async () => {
    const user = await boot();
    act(() => row('One').focus());
    await user.keyboard('{Shift>}{ArrowDown}{/Shift}{Meta>}{Enter}{/Meta}');
    expect(await screen.findByText('2 tasks completed')).toBeInTheDocument();
    await waitFor(() => expect(titles('Backlog')).toEqual(['Three', 'Four']), { timeout: 3000 });
    act(() => row('Three').focus());
    await user.keyboard('{Shift>}{ArrowDown}{/Shift}{Meta>}{Backspace}{/Meta}');
    expect(await screen.findByText('2 tasks deleted')).toBeInTheDocument();
    expect(titles('Backlog')).toEqual([]);
  });
});
