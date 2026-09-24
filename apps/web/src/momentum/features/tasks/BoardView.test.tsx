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

async function boot(backlog = ['One', 'Two', 'Three'], done: string[] = ['Shipped']) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'Done'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': backlog, 'sec-2': done } }),
  );
  window.history.replaceState(null, '', '/projects/seed-1/board');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('listitem', { name: backlog.at(-1) });
  return user;
}

const card = (name: string) => screen.getByRole('listitem', { name });
const cardsIn = (column: string) =>
  within(screen.getByRole('list', { name: `Cards in ${column}` }))
    .queryAllByRole('listitem')
    .map((li) => li.getAttribute('aria-label'));

describe('Board view', () => {
  it('renders columns from sections, with cards grouped and counted', async () => {
    await boot();
    expect(screen.getByRole('region', { name: 'Column Backlog' })).toBeInTheDocument();
    expect(cardsIn('Backlog')).toEqual(['One', 'Two', 'Three']);
    expect(cardsIn('Done')).toEqual(['Shipped']);
    expect(within(screen.getByRole('region', { name: 'Column Backlog' })).getByText('3')).toBeInTheDocument();
  });

  it('clicking a card opens the task pane; the checkbox does not', async () => {
    const user = await boot();
    await user.click(card('One'));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    expect(pane).toBeInTheDocument();
    act(() => pane.focus());
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull());

    await user.click(within(card('Two')).getByRole('checkbox'));
    await waitFor(() => expect(within(card('Two')).getByRole('checkbox')).toBeChecked());
    expect(screen.queryByRole('complementary', { name: 'Task details' })).toBeNull();
  });

  it('arrow keys move focus between and within columns', async () => {
    await boot();
    act(() => card('One').focus());
    await userEvent.setup().keyboard('{ArrowDown}');
    expect(card('Two')).toHaveFocus();
    await userEvent.setup().keyboard('{ArrowRight}');
    expect(card('Shipped')).toHaveFocus();
    await userEvent.setup().keyboard('{ArrowLeft}');
    expect(card('Two')).toHaveFocus();
  });

  it('⌘→ moves the focused card to the next column, with an undo toast', async () => {
    const user = await boot();
    act(() => card('One').focus());
    await user.keyboard('{Meta>}{ArrowRight}{/Meta}');
    await waitFor(() => expect(cardsIn('Done')).toEqual(['Shipped', 'One']));
    expect(cardsIn('Backlog')).toEqual(['Two', 'Three']);
    expect(await screen.findByText('Moved to Done')).toBeInTheDocument();
  });

  it('adds a card to a column', async () => {
    const user = await boot();
    await user.click(
      within(screen.getByRole('region', { name: 'Column Done' })).getByRole('button', { name: 'Add card' }),
    );
    await user.type(screen.getByRole('textbox', { name: 'New card title' }), 'Fresh card{Enter}');
    await waitFor(() => expect(cardsIn('Done')).toContain('Fresh card'));
  });

  it('adds a new column', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Add column' }));
    await user.type(screen.getByRole('textbox', { name: 'New column name' }), 'Review{Enter}');
    expect(await screen.findByRole('region', { name: 'Column Review' })).toBeInTheDocument();
  });

  it('renames a column inline', async () => {
    const user = await boot();
    const column = within(screen.getByRole('region', { name: 'Column Backlog' }));
    await user.click(column.getByRole('button', { name: /Column name: Backlog/ }));
    const input = column.getByRole('textbox', { name: 'Column name' });
    await user.clear(input);
    await user.type(input, 'To do{Enter}');
    expect(await screen.findByRole('region', { name: 'Column To do' })).toBeInTheDocument();
  });
});
