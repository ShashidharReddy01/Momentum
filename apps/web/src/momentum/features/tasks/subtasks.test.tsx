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

async function boot() {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'Done'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First', 'Second'] } }),
  );
  window.history.replaceState(null, '', '/projects/seed-1');
  render(<MomentumApp />);
  const user = userEvent.setup();
  await screen.findByRole('listitem', { name: 'Second' });
  return user;
}

const pane = () => screen.getByRole('complementary', { name: 'Task details' });
const subtaskTitles = (scope: HTMLElement) =>
  within(within(scope).getByRole('list', { name: 'Subtasks' }))
    .queryAllByRole('listitem')
    .map((li) => li.getAttribute('aria-label'))
    .filter((x) => x !== 'New task');

describe('Subtasks', () => {
  it('adds subtasks in the pane with Enter, counts them on the row, and completes one', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    await waitFor(() =>
      expect(within(pane()).getByRole('textbox', { name: 'Task name' })).toHaveValue('First'),
    );
    await user.click(within(pane()).getByRole('button', { name: /Add subtask/ }));
    const input = within(pane()).getByRole('textbox', { name: 'New task name' });
    await user.type(input, 'Draft outline{Enter}');
    await user.type(within(pane()).getByRole('textbox', { name: 'New task name' }), 'Review{Enter}');
    await user.type(within(pane()).getByRole('textbox', { name: 'New task name' }), 'Publish{Enter}{Escape}');
    // rapid adds keep their order on the server too (regression: stale anchors reordered them)
    await waitFor(() => expect(subtaskTitles(pane())).toEqual(['Draft outline', 'Review', 'Publish']));
    await user.click(within(pane()).getByRole('button', { name: 'Close details' }));
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    await waitFor(() => expect(subtaskTitles(pane())).toEqual(['Draft outline', 'Review', 'Publish']));
    // the list row shows the count
    const row = screen.getByRole('listitem', { name: 'First' });
    await waitFor(() =>
      expect(within(row).getByRole('button', { name: /0 of 3 subtasks/ })).toBeInTheDocument(),
    );
    await user.click(within(pane()).getByRole('checkbox', { name: 'Complete Draft outline' }));
    await waitFor(() =>
      expect(within(row).getByRole('button', { name: /1 of 3 subtasks/ })).toBeInTheDocument(),
    );
  });

  it('opens a subtask in the pane with a way back to its parent', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for First' }));
    await user.click(await within(pane()).findByRole('button', { name: /Add subtask/ }));
    await user.type(within(pane()).getByRole('textbox', { name: 'New task name' }), 'Child{Enter}{Escape}');
    await user.click(await within(pane()).findByRole('button', { name: 'Open Child' }));
    await waitFor(() =>
      expect(within(pane()).getByRole('textbox', { name: 'Task name' })).toHaveValue('Child'),
    );
    await user.click(within(pane()).getByRole('button', { name: /Subtask of First/ }));
    await waitFor(() =>
      expect(within(pane()).getByRole('textbox', { name: 'Task name' })).toHaveValue('First'),
    );
  });

  it('Tab on a new list row makes it a subtask of the row above; Shift+Tab turns it back', async () => {
    const user = await boot();
    await user.click(screen.getByRole('button', { name: 'First' })); // edit the name…
    await user.keyboard('{Enter}'); // …Enter opens a new row below it
    await user.type(screen.getByRole('textbox', { name: 'New task name' }), 'Indented');
    await user.keyboard('{Tab}');
    // now an add-subtask row under First, keeping the text
    const sub = await screen.findByRole('textbox', { name: 'New task name' });
    expect(sub).toHaveValue('Indented');
    expect(sub).toHaveAttribute('placeholder', 'Subtask name');
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    const top = await screen.findByRole('textbox', { name: 'New task name' });
    expect(top).toHaveAttribute('placeholder', 'Write a task name');
    expect(top).toHaveValue('Indented');
    await user.keyboard('{Tab}');
    await user.type(await screen.findByPlaceholderText('Subtask name'), '{Enter}{Escape}');
    const row = screen.getByRole('listitem', { name: 'First' });
    await waitFor(() =>
      expect(within(row).getByRole('button', { name: /0 of 1 subtasks/ })).toBeInTheDocument(),
    );
    // the inline list under First shows it (expanded)
    const lists = screen.getAllByRole('list', { name: 'Subtasks' });
    expect(within(lists[0]!).getByRole('listitem', { name: 'Indented' })).toBeInTheDocument();
    // collapse via the badge
    await user.click(within(row).getByRole('button', { name: /hide/ }));
    expect(screen.queryByRole('list', { name: 'Subtasks' })).toBeNull();
    act(() => undefined);
  });
});
