import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiChatHandlers, aiCommandHandlers } from '@/mocks/ai';
import { authHandlers } from '@/mocks/handlers';
import { multiHomingHandlers } from '@/mocks/multiHoming';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';
import { suggestionsFor } from './suggestions';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

async function boot(opts: { path?: string; aiEnabled?: boolean } = {}) {
  const chat = aiChatHandlers([]);
  server.use(
    ...authHandlers({ loggedIn: true, config: { ai_enabled: opts.aiEnabled ?? true } }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog', 'Done'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First', 'Second', 'Third'] } }),
    ...multiHomingHandlers(
      '',
      [{ id: 'seed-1', name: 'Website Revamp', color: null }],
      ['task-1', 'task-2', 'task-3'].map((task_id) => ({
        task_id,
        project_id: 'seed-1',
        section_id: 'sec-1',
        position: '100000',
      })),
    ),
    ...chat.handlers,
    ...aiCommandHandlers([]).handlers,
  );
  window.history.replaceState(null, '', opts.path ?? '/projects/seed-1');
  render(<MomentumApp />);
  await screen.findByRole('listitem', { name: 'First' });
  return { user: userEvent.setup(), chat };
}

const panel = () => screen.getByRole('complementary', { name: 'Ask Mo' });

describe('Ask Mo about this (S3.3.2)', () => {
  it('from the task pane: a chat pinned to the task, with task suggestions', async () => {
    const { user, chat } = await boot();
    await user.click(screen.getByRole('button', { name: 'Open details for Second' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    await user.click(within(pane).getByRole('button', { name: 'Ask Mo about this task' }));
    expect(await within(panel()).findByLabelText(/Chat is about T-\d+ Second/)).toBeInTheDocument();
    const suggested = within(panel()).getByRole('group', { name: 'Suggested questions' });
    await user.click(within(suggested).getByRole('button', { name: 'Summarize this task' }));
    await waitFor(() => expect(chat.requests).toHaveLength(1));
    expect(chat.requests[0]).toEqual({
      text: 'Summarize this task',
      screen: { kind: 'task', task_id: 'task-2' },
      conversation_id: null,
    });
    // unpinned: back to what's on screen (the project, with the open task)
    await user.click(within(panel()).getByRole('button', { name: 'Stop asking about this' }));
    await user.type(within(panel()).getByRole('textbox', { name: 'Message Mo' }), 'And now?{Enter}');
    await waitFor(() => expect(chat.requests).toHaveLength(2));
    expect(chat.requests[1]!.screen).toEqual({ kind: 'project', project_id: 'seed-1', task_id: 'task-2' });
  });

  it('from the project header and from a selection', async () => {
    const { user, chat } = await boot();
    await user.click(screen.getByRole('button', { name: 'Ask Mo about this project' }));
    expect(await within(panel()).findByLabelText('Chat is about Website Revamp')).toBeInTheDocument();
    await user.click(within(panel()).getByRole('button', { name: "What's blocking this project?" }));
    await waitFor(() => expect(chat.requests).toHaveLength(1));
    expect(chat.requests[0]!.screen).toEqual({ kind: 'project', project_id: 'seed-1' });

    act(() => screen.getByRole('listitem', { name: 'First' }).focus());
    await user.keyboard('{Shift>}{ArrowDown}{/Shift}');
    const bar = screen.getByRole('toolbar', { name: '2 tasks selected' });
    await user.click(within(bar).getByRole('button', { name: 'Ask Mo about these tasks' }));
    expect(await within(panel()).findByLabelText('Chat is about 2 selected tasks')).toBeInTheDocument();
    // a new chat: the project question is gone
    expect(within(panel()).queryByRole('region', { name: /Question:/ })).toBeNull();
    await user.click(within(panel()).getByRole('button', { name: 'Summarize these tasks' }));
    await waitFor(() => expect(chat.requests).toHaveLength(2));
    expect(chat.requests[1]).toEqual({
      text: 'Summarize these tasks',
      screen: { kind: 'project', project_id: 'seed-1', selected_task_ids: ['task-1', 'task-2'] },
      conversation_id: null,
    });
  });

  it('AI off: no Ask Mo buttons, and the panel says Mo is off instead of taking messages', async () => {
    const { user } = await boot({ aiEnabled: false });
    expect(screen.queryByRole('button', { name: 'Ask Mo about this project' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Open details for Second' }));
    const pane = await screen.findByRole('complementary', { name: 'Task details' });
    expect(within(pane).queryByRole('button', { name: 'Ask Mo about this task' })).toBeNull();
    await user.keyboard('{Control>}j{/Control}');
    expect(await within(panel()).findByText('Mo is turned off for this workspace.')).toBeInTheDocument();
    expect(within(panel()).queryByRole('textbox', { name: 'Message Mo' })).toBeNull();
  });
});

describe('suggestionsFor', () => {
  it('follows the pinned context first, then the screen', () => {
    expect(suggestionsFor({ kind: 'home' }, null)[0]).toBe("What's due today?");
    expect(suggestionsFor({ kind: 'project', project_id: 'p', task_id: 't' }, null)[0]).toBe(
      'Summarize this task',
    );
    expect(suggestionsFor({ kind: 'my_tasks' }, null)[0]).toBe('What should I work on first?');
    expect(
      suggestionsFor(
        { kind: 'home' },
        { id: 1, kind: 'selection', label: '2 selected tasks', taskIds: [] },
      )[0],
    ).toBe('Summarize these tasks');
    expect(suggestionsFor({ kind: 'search' }, null)).toEqual(["What's overdue?", 'What changed this week?']);
  });
});
