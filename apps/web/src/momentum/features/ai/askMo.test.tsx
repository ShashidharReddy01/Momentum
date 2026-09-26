import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import {
  aiActionFixture,
  aiChatHandlers,
  aiCommandHandlers,
  aiHandlers,
  aiMemoryHandlers,
  type ScriptedEvent,
} from '@/mocks/ai';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { searchHandlers } from '@/mocks/search';
import { teamHandlers } from '@/mocks/teams';
import { runsFromMessages } from './useMoRuns';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const T12 = {
  ref: '[T-12]',
  type: 'task',
  valid: true,
  id: 'task-12',
  key: 'T-12',
  title: 'Sign vendor contract',
};
const T99 = { ref: '[T-99]', type: 'task', valid: false, id: 'task-99', key: 'T-99', title: null };
const P1 = {
  ref: '[P:Website Revamp]',
  type: 'project',
  valid: true,
  id: 'p-web',
  key: null,
  title: 'Website Revamp',
};

const J8: ScriptedEvent[] = [
  ['conversation', { conversation_id: 'conv-1', user_message_id: 'm-1' }],
  ['tool_call', { id: 'c1', name: 'semantic_search' }],
  ['tool_result', { id: 'c1', name: 'semantic_search', ok: true, summary: '2 result(s)', preview: false }],
  ['token', { text: 'Launch is blocked by [T-12] in [P:Website Revamp].' }],
  ['token', { text: '\n- **Legal** still reviews [T-99]' }],
  ['citation', T12],
  ['citation', P1],
  ['citation', T99],
  ['done', { steps: 2, message_id: 'm-2', grounded: true }],
];

async function boot(
  chatScripts: ScriptedEvent[][],
  opts: { path?: string; stored?: Parameters<typeof aiChatHandlers>[1] } = {},
) {
  const chat = aiChatHandlers(chatScripts, opts.stored ?? []);
  const cmd = aiCommandHandlers([]);
  const ai = aiHandlers([aiActionFixture({ id: 'act-9', source: 'chat' })]);
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...searchHandlers(),
    ...chat.handlers,
    ...cmd.handlers,
    ...ai.handlers,
    ...aiMemoryHandlers([]).handlers,
  );
  window.history.replaceState(null, '', opts.path ?? '/');
  render(<MomentumApp />);
  await screen.findByRole('heading', { level: 1 });
  return { user: userEvent.setup(), chat, cmd };
}

async function openPanelAndAsk(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.keyboard('{Control>}j{/Control}');
  const panel = await screen.findByRole('complementary', { name: 'Ask Mo' });
  await user.type(within(panel).getByRole('textbox', { name: 'Message Mo' }), `${text}{Enter}`);
  return panel;
}

describe('Ask Mo chat (S3.3.1)', () => {
  it('J8 shape: a question streams an answer whose citations link only when valid', async () => {
    const { user, chat, cmd } = await boot([J8]);
    const panel = await openPanelAndAsk(user, "What's blocking launch?");
    const q = await within(panel).findByRole('region', { name: "Question: What's blocking launch?" });
    expect(await within(q).findByText('Searched content')).toBeInTheDocument();
    const answer = within(q).getByRole('group', { name: "Mo's answer (AI)" });
    const link = await within(answer).findByRole('link', { name: 'T-12 Sign vendor contract' });
    expect(link).toHaveAttribute('href', '/task/task-12');
    expect(within(answer).getByRole('link', { name: 'Project Website Revamp' })).toHaveAttribute(
      'href',
      '/projects/p-web',
    );
    // a reference Mo made that isn't valid for me stays text, never a link
    expect(within(answer).getByText('[T-99]').closest('a')).toBeNull();
    expect(within(answer).getByText('Legal').tagName).toBe('STRONG');
    expect(within(answer).getByRole('listitem')).toHaveTextContent('Legal still reviews [T-99]');
    // chat, not a ⌘K command
    expect(cmd.requests).toEqual([]);
    expect(chat.requests).toEqual([
      { text: "What's blocking launch?", screen: { kind: 'home' }, conversation_id: null },
    ]);
  });

  it('a follow-up continues the conversation; New chat starts another', async () => {
    const { user, chat } = await boot([J8, [['conversation', { conversation_id: 'conv-1' }]], []]);
    const panel = await openPanelAndAsk(user, "What's blocking launch?");
    await within(panel).findByRole('link', { name: 'T-12 Sign vendor contract' });
    await user.type(within(panel).getByRole('textbox', { name: 'Message Mo' }), 'Who owns it?{Enter}');
    await waitFor(() => expect(chat.requests).toHaveLength(2));
    expect(chat.requests[1]!.conversation_id).toBe('conv-1');
    await user.click(within(panel).getByRole('button', { name: 'New chat' }));
    expect(within(panel).queryByRole('region', { name: /Question:/ })).toBeNull();
    await user.type(within(panel).getByRole('textbox', { name: 'Message Mo' }), 'Hello{Enter}');
    await waitFor(() => expect(chat.requests).toHaveLength(3));
    expect(chat.requests[2]!.conversation_id).toBeNull();
  });

  it('rates an answer and marks an answer with no workspace sources', async () => {
    const { user, chat } = await boot([
      [
        ['conversation', { conversation_id: 'conv-2' }],
        ['token', { text: "I couldn't find anything about that in the workspace." }],
        ['done', { steps: 1, message_id: 'm-7', grounded: false }],
      ],
    ]);
    const panel = await openPanelAndAsk(user, 'zebra?');
    expect(await within(panel).findByText('No sources from your workspace cited.')).toBeInTheDocument();
    const down = within(panel).getByRole('button', { name: 'Bad answer' });
    await user.click(down);
    await waitFor(() => expect(down).toHaveAttribute('aria-pressed', 'true'));
    expect(chat.feedback).toEqual([{ target_type: 'ai_message', target_id: 'm-7', rating: -1 }]);
  });

  it('a change Mo suggests in chat shows as a PreviewCard; errors are shown', async () => {
    const { user } = await boot([
      [
        ['conversation', { conversation_id: 'conv-3' }],
        ['token', { text: 'T-12 will be marked complete once you apply the preview.' }],
        ['action_proposed', { action_id: 'act-9', summary: 'Would complete T-12', risk: 'low' }],
        ['done', { steps: 2, message_id: 'm-9', grounded: false }],
      ],
      [
        ['conversation', { conversation_id: 'conv-3' }],
        ['error', { reason: 'timeout', message: 'Mo is unavailable right now. Try again shortly.' }],
      ],
    ]);
    const panel = await openPanelAndAsk(user, 'Complete T-12');
    expect(await within(panel).findByRole('region', { name: 'Mo suggests (AI)' })).toBeInTheDocument();
    await user.type(within(panel).getByRole('textbox', { name: 'Message Mo' }), 'And again{Enter}');
    expect(await within(panel).findByRole('alert')).toHaveTextContent('Mo is unavailable right now');
  });

  it('/ask lists conversations, opens one from history, and a new question moves the URL', async () => {
    const stored = [
      {
        conversation: {
          id: 'conv-old',
          title: 'What is overdue?',
          context_type: 'global' as const,
          context_id: null,
          created_at: '2026-09-25T10:00:00Z',
          updated_at: '2026-09-25T10:00:00Z',
        },
        messages: [
          { id: 'u1', role: 'user' as const, text: 'What is overdue?', created_at: '2026-09-25T10:00:00Z' },
          {
            id: 'a1',
            role: 'assistant' as const,
            text: 'Only [T-12] is overdue.',
            steps: [{ name: 'search_tasks', ok: true }],
            citations: [T12 as never],
            grounded: true,
            rating: 1 as const,
            created_at: '2026-09-25T10:00:01Z',
          },
        ],
      },
    ];
    const { user, chat } = await boot(
      [
        [
          ['conversation', { conversation_id: 'conv-new' }],
          ['done', {}],
        ],
      ],
      {
        path: '/ask',
        stored,
      },
    );
    expect(await screen.findByText('Ask Mo about your work')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Conversations' });
    await user.click(await within(nav).findByRole('link', { name: 'What is overdue?' }));
    const q = await screen.findByRole('region', { name: 'Question: What is overdue?' });
    expect(within(q).getByRole('link', { name: 'T-12 Sign vendor contract' })).toBeInTheDocument();
    expect(within(q).getByRole('button', { name: 'Good answer' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(q).getByText('Searched tasks')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/ask/conv-old');

    await user.click(screen.getByRole('button', { name: /New chat/ }));
    await waitFor(() => expect(window.location.pathname).toBe('/ask'));
    expect(screen.queryByRole('region', { name: 'Question: What is overdue?' })).toBeNull();
    const main = screen.getByRole('region', { name: 'New chat' });
    await user.type(within(main).getByRole('textbox', { name: 'Message Mo' }), 'Plan?{Enter}');
    await waitFor(() => expect(window.location.pathname).toBe('/ask/conv-new'));
    expect(await screen.findByRole('region', { name: 'Question: Plan?' })).toBeInTheDocument();
    expect(chat.requests.at(-1)!.conversation_id).toBeNull();
  });
});

describe('runsFromMessages', () => {
  it('pairs questions with answers and marks a question left without one', () => {
    const runs = runsFromMessages([
      { id: 'u1', role: 'user', text: 'a', created_at: '' },
      { id: 'u2', role: 'user', text: 'b', created_at: '' },
      { id: 'a2', role: 'assistant', text: 'B', created_at: '' },
    ]);
    expect(runs.map((r) => [r.text, r.status, r.reply])).toEqual([
      ['a', 'error', ''],
      ['b', 'done', 'B'],
    ]);
  });
});
