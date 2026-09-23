import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
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

function useHandlers() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'Done'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['Charlie', 'alpha', 'Bravo'], 'sec-2': ['Delta'] } }),
  );
}

async function open(path = '/projects/seed-1') {
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  await screen.findByRole('listitem', { name: 'Delta' });
  return userEvent.setup();
}

const visible = () =>
  screen
    .queryAllByRole('listitem')
    .filter((li) => li.hasAttribute('data-task-id'))
    .map((li) => li.getAttribute('aria-label'));
const row = (name: string) => screen.getByRole('listitem', { name });

async function assignToMe(user: ReturnType<typeof userEvent.setup>, name: string) {
  act(() => row(name).focus());
  await user.keyboard('m');
  await within(row(name)).findByRole('button', { name: /Assignee: Ravi/ });
}

describe('Filter, sort, group', () => {
  it('sorts alphabetically, reflects the view in the URL, and restores it on revisit', async () => {
    useHandlers();
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Sort' }));
    await user.click(await screen.findByRole('menuitemradio', { name: /Alphabetical/ }));
    expect(visible()).toEqual(['alpha', 'Bravo', 'Charlie', 'Delta']);
    expect(window.location.search).toContain('sort=title');
    expect(screen.getByText(/Drag to reorder is off/)).toBeInTheDocument();
    // leave and come back without params: saved prefs restore the view (after the debounce)
    await new Promise((r) => setTimeout(r, 700));
    cleanup();
    await open();
    await waitFor(() => expect(visible()).toEqual(['alpha', 'Bravo', 'Charlie', 'Delta']));
    await waitFor(() => expect(window.location.search).toContain('sort=title'));
    await user.click(screen.getByRole('button', { name: 'Back to drag order' }));
    expect(visible()).toEqual(['Charlie', 'alpha', 'Bravo', 'Delta']);
  });

  it('a shared URL reproduces the view (and invalid params are ignored)', async () => {
    useHandlers();
    await open('/projects/seed-1?sort=title&group=bogus&task=x');
    expect(visible()).toEqual(['alpha', 'Bravo', 'Charlie', 'Delta']);
    expect(screen.getByRole('button', { name: 'Sort: Alphabetical' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Group' })).toBeInTheDocument();
  });

  it('"Just my tasks" filters; an edited row stays until the view changes; empty state clears', async () => {
    useHandlers();
    const user = await open();
    await assignToMe(user, 'alpha');
    await user.click(screen.getByRole('button', { name: 'Filter' }));
    await user.click(screen.getByRole('checkbox', { name: 'Just my tasks' }));
    await user.keyboard('{Escape}');
    expect(visible()).toEqual(['alpha']);
    expect(window.location.search).toContain('assignee=me');
    // unassigning keeps the row visible (sticky) instead of vanishing under the cursor
    await user.click(within(row('alpha')).getByRole('button', { name: /Assignee: Ravi/ }));
    await user.click(await screen.findByRole('option', { name: /Unassign/ }));
    await waitFor(() =>
      expect(within(row('alpha')).getByRole('button', { name: 'Assign' })).toBeInTheDocument(),
    );
    expect(visible()).toEqual(['alpha']);
    // changing the view applies the filter for real → empty state
    await user.click(screen.getByRole('button', { name: /Filter/ }));
    await user.click(screen.getByRole('button', { name: 'Due today' }));
    await user.keyboard('{Escape}');
    expect(await screen.findByText('No tasks match these filters.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(visible()).toEqual(['Charlie', 'alpha', 'Bravo', 'Delta']);
  });

  it('groups by assignee with Unassigned last and keeps keyboard navigation in group order', async () => {
    useHandlers();
    const user = await open();
    await assignToMe(user, 'Bravo');
    await user.click(screen.getByRole('button', { name: 'Group' }));
    await user.click(await screen.findByRole('menuitemradio', { name: /Assignee/ }));
    const groups = screen
      .getAllByRole('region')
      .map((r) => r.getAttribute('aria-label'))
      .filter((l) => l?.startsWith('Group '));
    expect(groups).toEqual(['Group Ravi Kumar (you)', 'Group Unassigned']);
    expect(visible()).toEqual(['Bravo', 'Charlie', 'alpha', 'Delta']);
    act(() => row('Bravo').focus());
    await user.keyboard('{ArrowDown}');
    expect(row('Charlie')).toHaveFocus();
    // no add-task rows or section menus in a grouped view
    expect(screen.queryByRole('button', { name: /Add task/ })).toBeNull();
  });
});
