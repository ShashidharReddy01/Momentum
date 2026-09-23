import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { myMoves, taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  myMoves.length = 0;
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

async function boot(assigned = ['Alpha', 'Bravo', 'Charlie']) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'Done'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['Alpha', 'Bravo', 'Charlie', 'Not mine'] } }, 15, assigned),
  );
  window.history.replaceState(null, '', '/my-tasks');
  render(<MomentumApp />);
  const user = userEvent.setup();
  if (assigned.length) await screen.findByRole('listitem', { name: assigned[0] });
  return user;
}

const titles = (bucket: string) =>
  within(screen.getByRole('list', { name: `Tasks in ${bucket}` }))
    .queryAllByRole('listitem')
    .filter((li) => li.hasAttribute('data-task-id'))
    .map((li) => li.getAttribute('aria-label'));
const row = (name: string) => screen.getByRole('listitem', { name });

describe('My Tasks', () => {
  it('lists only my open tasks, newest assignments in "Recently assigned", with the project shown', async () => {
    await boot();
    expect(titles('Recently assigned')).toHaveLength(3);
    expect(screen.queryByRole('listitem', { name: 'Not mine' })).toBeNull();
    expect(titles('Today')).toEqual([]);
    expect(screen.getByText('3 open tasks assigned to you')).toBeInTheDocument();
    expect(within(row('Alpha')).getAllByText('Website Revamp').length).toBeGreaterThan(0);
  });

  it('shows a friendly empty state when nothing is assigned', async () => {
    await boot([]);
    expect(await screen.findByText('Nothing assigned to you')).toBeInTheDocument();
  });

  it('⌘↓ moves a task within its bucket and across into the next one (with undo toast)', async () => {
    const user = await boot();
    const [first, second, third] = titles('Recently assigned') as string[];
    act(() => row(first!).focus());
    await user.keyboard('{Meta>}{ArrowDown}{/Meta}');
    expect(titles('Recently assigned')).toEqual([second, first, third]);
    await user.keyboard('{Meta>}{ArrowDown}{/Meta}');
    await user.keyboard('{Meta>}{ArrowDown}{/Meta}');
    await waitFor(() => expect(titles('Today')).toEqual([first]));
    expect(titles('Recently assigned')).toEqual([second, third]);
    expect(await screen.findByText('Moved to Today')).toBeInTheDocument();
    await waitFor(() => expect(myMoves.at(-1)).toMatchObject({ bucket: 'today' }));
    // survives a reload from the server
    cleanup();
    window.history.replaceState(null, '', '/my-tasks');
    render(<MomentumApp />);
    await screen.findByRole('listitem', { name: first });
    expect(titles('Today')).toEqual([first]);
    act(() => row(first!).focus());
    await userEvent.setup().keyboard('{Meta>}{ArrowUp}{/Meta}');
    await waitFor(() => expect(titles('Recently assigned')).toEqual([second, third, first]));
  });

  it('completing a task removes it; "Show completed" lists it and can reopen it', async () => {
    const user = await boot();
    await user.click(within(row('Bravo')).getByRole('checkbox'));
    await waitFor(() => expect(screen.queryByRole('listitem', { name: 'Bravo' })).toBeNull(), {
      timeout: 3000,
    });
    expect(screen.getByText('2 open tasks assigned to you')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Show completed/ }));
    const done = await screen.findByRole('list', { name: 'Completed tasks' });
    const bravo = await within(done).findByRole('listitem', { name: 'Bravo' });
    await user.click(within(bravo).getByRole('checkbox'));
    await waitFor(() => expect(titles('Recently assigned')).toContain('Bravo'));
  });

  it('collapsing a bucket is remembered', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Collapse Recently assigned' }));
    expect(screen.queryByRole('list', { name: 'Tasks in Recently assigned' })).toBeNull();
    cleanup();
    window.history.replaceState(null, '', '/my-tasks');
    render(<MomentumApp />);
    expect(await screen.findByRole('button', { name: 'Expand Recently assigned' })).toBeInTheDocument();
  });
});
