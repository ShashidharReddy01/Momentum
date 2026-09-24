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
import { toISODate } from '@/lib/dates';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

async function boot(titles: string[] = ['Undated one', 'Undated two']) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'Done'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': titles } }),
  );
  window.history.replaceState(null, '', '/projects/seed-1/calendar');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findAllByRole('gridcell');
  return user;
}

const cell = (iso: string) => document.querySelector<HTMLElement>(`[data-date="${iso}"]`)!;
const cellTasks = (iso: string) =>
  within(cell(iso))
    .queryAllByRole('listitem')
    .map((li) => li.getAttribute('aria-label'));

describe('Calendar view', () => {
  it('lists tasks with no due date in the No date tray', async () => {
    await boot(['Undated one', 'Undated two']);
    const tray = screen.getByRole('complementary', { name: 'No date' });
    expect(
      within(tray)
        .getAllByRole('listitem')
        .map((li) => li.getAttribute('aria-label')),
    ).toEqual(['Undated one', 'Undated two']);
  });

  it('adding a task on a day sets its due date to that day', async () => {
    const user = await boot([]);
    const today = toISODate(new Date());
    await user.click(within(cell(today)).getByRole('button', { name: 'Add task' }));
    await user.type(screen.getByRole('textbox', { name: 'New task title' }), 'Ship it{Enter}');
    await waitFor(() => expect(cellTasks(today)).toContain('Ship it'));
  });

  it('clicking a task chip opens the task pane; the checkbox does not', async () => {
    const user = await boot([]);
    const today = toISODate(new Date());
    await user.click(within(cell(today)).getByRole('button', { name: 'Add task' }));
    await user.type(screen.getByRole('textbox', { name: 'New task title' }), 'Reviewed{Enter}');
    await waitFor(() => expect(cellTasks(today)).toContain('Reviewed'));

    const chip = screen.getByRole('listitem', { name: 'Reviewed' });
    await user.click(chip);
    expect(await screen.findByRole('complementary', { name: 'Task details' })).toBeInTheDocument();
    const pane = screen.getByRole('complementary', { name: 'Task details' });
    act(() => pane.focus());
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull());

    await user.click(within(chip).getByRole('checkbox'));
    await waitFor(() => expect(within(chip).getByRole('checkbox')).toBeChecked());
    expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull();
  });

  it('⌘→ reschedules the focused task by one day, with an undo toast', async () => {
    const user = await boot([]);
    const today = new Date();
    const todayIso = toISODate(today);
    const tomorrowIso = toISODate(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1));
    await user.click(within(cell(todayIso)).getByRole('button', { name: 'Add task' }));
    await user.type(screen.getByRole('textbox', { name: 'New task title' }), 'Nudge me{Enter}');
    await waitFor(() => expect(cellTasks(todayIso)).toContain('Nudge me'));

    act(() => screen.getByRole('listitem', { name: 'Nudge me' }).focus());
    await user.keyboard('{Meta>}{ArrowRight}{/Meta}');
    await waitFor(() => expect(cellTasks(tomorrowIso)).toContain('Nudge me'));
    expect(cellTasks(todayIso)).not.toContain('Nudge me');
    expect(await screen.findByText(/Moved to/)).toBeInTheDocument();
  });

  it('toggles between month and week, changing the number of visible days', async () => {
    const user = await boot([]);
    expect(screen.getAllByRole('gridcell')).toHaveLength(42);
    await user.click(screen.getByRole('button', { name: 'week' }));
    expect(screen.getAllByRole('gridcell')).toHaveLength(7);
    await user.click(screen.getByRole('button', { name: 'month' }));
    expect(screen.getAllByRole('gridcell')).toHaveLength(42);
  });

  it('next/previous navigation changes the visible period label, and Today resets it', async () => {
    const user = await boot([]);
    const label = () => screen.getByText(/\d{4}/).textContent;
    const initial = label();
    await user.click(screen.getByRole('button', { name: 'Next month' }));
    expect(label()).not.toBe(initial);
    await user.click(screen.getByRole('button', { name: 'Today' }));
    expect(label()).toBe(initial);
  });
});
