import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { DueText } from '@/components/common/DueText';
import { addDays, toISODate } from '@/lib/dates';
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

async function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['Write brief'] } }),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  const row = await screen.findByRole('listitem', { name: 'Write brief' });
  return { user, row };
}

describe('Assignee and due date', () => {
  it('A opens the assignee picker; typing + Enter assigns', async () => {
    const { user, row } = await boot();
    row.focus();
    await user.keyboard('a');
    const search = await screen.findByPlaceholderText('Assign to…');
    expect(search).toHaveFocus();
    await user.type(search, 'ana{Enter}');
    await waitFor(() =>
      expect(within(row).getByRole('button', { name: /Assignee: Ana/ })).toBeInTheDocument(),
    );
    expect(await screen.findByText(/Assigned to Ana/)).toBeInTheDocument();
    expect(row).toHaveFocus();
  });

  it('M assigns to me; the picker offers Unassign', async () => {
    const { user, row } = await boot();
    row.focus();
    await user.keyboard('m');
    const cell = await within(row).findByRole('button', { name: 'Assignee: Ravi Kumar' });
    await user.click(cell);
    expect(screen.queryByRole('option', { name: /Assign to me/ })).toBeNull();
    await user.click(screen.getByRole('option', { name: /Unassign/ }));
    await waitFor(() => expect(within(row).getByRole('button', { name: 'Assign' })).toBeInTheDocument());
  });

  it('D opens the date picker; natural language + Enter sets the due date', async () => {
    const { user, row } = await boot();
    row.focus();
    await user.keyboard('d');
    const input = await screen.findByRole('textbox', { name: 'Due date' });
    await user.type(input, 'tomorrow');
    expect(screen.getByText('↵ Tomorrow')).toBeInTheDocument();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(within(row).getByText('Tomorrow')).toBeInTheDocument());
    // unreadable input does nothing on Enter
    row.focus();
    await user.keyboard('d');
    await user.type(await screen.findByRole('textbox', { name: 'Due date' }), 'blah{Enter}');
    expect(screen.getByText("Couldn't read that date")).toBeInTheDocument();
    await user.keyboard('{Escape}');
    // No date clears it
    await user.click(within(row).getByRole('button', { name: /^Due / }));
    await user.click(screen.getByRole('button', { name: 'No date' }));
    await waitFor(() =>
      expect(within(row).getByRole('button', { name: 'Set due date' })).toBeInTheDocument(),
    );
  });

  it('calendar supports arrow keys and Enter', async () => {
    const { user, row } = await boot();
    await user.click(within(row).getByRole('button', { name: 'Set due date' }));
    const grid = await screen.findByRole('grid');
    const todayCell = within(grid)
      .getAllByRole('gridcell')
      .find((c) => c.getAttribute('data-date') === toISODate(new Date()))!;
    todayCell.focus();
    await user.keyboard('{ArrowDown}{ArrowRight}');
    const target = toISODate(addDays(new Date(), 8));
    expect(document.activeElement?.getAttribute('data-date')).toBe(target);
    await user.keyboard('{Enter}');
    await waitFor(() =>
      expect(within(row).queryByRole('button', { name: 'Set due date' })).not.toBeInTheDocument(),
    );
  });
});

describe('DueText', () => {
  it('shows overdue in crit and today in warn', () => {
    const { rerender, container } = render(<DueText dueOn={toISODate(addDays(new Date(), -2))} />);
    expect(container.querySelector('[data-tone="overdue"]')).toHaveClass('text-crit');
    rerender(<DueText dueOn={toISODate(new Date())} />);
    expect(screen.getByText('Today')).toHaveClass('text-warn');
    rerender(<DueText dueOn={toISODate(addDays(new Date(), -2))} done />);
    expect(container.querySelector('[data-tone="done"]')).toHaveClass('line-through');
  });
});
