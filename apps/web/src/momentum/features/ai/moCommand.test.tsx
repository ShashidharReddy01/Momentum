import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import {
  aiActionFixture,
  aiCommandHandlers,
  aiHandlers,
  aiMemoryHandlers,
  type ScriptedEvent,
} from '@/mocks/ai';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { searchHandlers } from '@/mocks/search';
import { teamHandlers } from '@/mocks/teams';
import { looksLikeInstruction } from './intent';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const J7: ScriptedEvent[] = [
  ['tool_call', { id: 'c1', name: 'search_tasks' }],
  ['tool_result', { id: 'c1', name: 'search_tasks', ok: true, summary: '2 task(s) found', preview: false }],
  ['tool_call', { id: 'c2', name: 'bulk_update_tasks' }],
  [
    'tool_result',
    { id: 'c2', name: 'bulk_update_tasks', ok: true, summary: 'Would update 2 of 2 task(s)', preview: true },
  ],
  ['token', { text: 'The overdue tasks in Website Revamp will be assigned to Ana Souza.' }],
  ['action_proposed', { action_id: 'act-1', summary: 'Would update 2 of 2 task(s)', risk: 'medium' }],
  ['done', { steps: 3 }],
];

async function boot(scripts: ScriptedEvent[][], opts: { aiEnabled?: boolean; path?: string } = {}) {
  const cmd = aiCommandHandlers(scripts);
  const ai = aiHandlers([aiActionFixture({ risk: 'medium', summary: 'Would update 2 of 2 task(s)' })]);
  server.use(
    ...authHandlers({ loggedIn: true, config: { ai_enabled: opts.aiEnabled ?? true } }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...searchHandlers(),
    ...cmd.handlers,
    ...ai.handlers,
    ...aiMemoryHandlers([]).handlers,
  );
  window.history.replaceState(null, '', opts.path ?? '/');
  render(<MomentumApp />);
  await screen.findByRole('heading', { level: 1 });
  return { user: userEvent.setup(), cmd, ai };
}

async function askFromPalette(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.keyboard('{Control>}k{/Control}');
  const palette = await screen.findByRole('dialog', { name: 'Command palette' });
  await user.type(within(palette).getByRole('combobox'), text);
  await user.click(await within(palette).findByRole('option', { name: /Ask Mo to do this/ }));
}

describe('⌘K natural-language commands (S3.2.2)', () => {
  it('J7 shape: ⌘K → Mo panel shows the work and a preview → apply', async () => {
    const { user, cmd, ai } = await boot([J7]);
    await askFromPalette(user, 'assign all overdue tasks in Website Revamp to Ana');
    const panel = await screen.findByRole('complementary', { name: 'Ask Mo' });
    const run = await within(panel).findByRole('region', {
      name: 'Request: assign all overdue tasks in Website Revamp to Ana',
    });
    expect(await within(run).findByText('Searched tasks · Previewed bulk update tasks')).toBeInTheDocument();
    expect(within(run).getByText(/will be assigned to Ana Souza/)).toBeInTheDocument();
    const card = await within(run).findByRole('region', { name: 'Mo suggests (AI)' });
    await user.click(within(card).getByRole('button', { name: 'Apply' }));
    expect(await within(card).findByText('Applied')).toBeInTheDocument();
    expect(cmd.requests).toEqual([
      { text: 'assign all overdue tasks in Website Revamp to Ana', screen: { kind: 'home' } },
    ]);
    expect(ai.calls.map((c) => c.path)).toEqual(['apply']);
  });

  it('sends the screen as context and offers candidates when the target is ambiguous', async () => {
    const { user, cmd } = await boot(
      [
        [
          ['tool_call', { id: 'c1', name: 'update_task' }],
          ['tool_result', { id: 'c1', name: 'update_task', ok: false, summary: 'ambiguous', preview: false }],
          ['token', { text: 'Several tasks match “pricing”. Which one do you mean?' }],
          [
            'clarify',
            {
              question: 'Several tasks match “pricing”. Which one do you mean?',
              candidates: [
                { key: 'T-12', title: 'Draft pricing copy', project: 'Website Revamp' },
                { key: 'T-13', title: 'Draft pricing FAQ', project: 'Website Revamp' },
              ],
            },
          ],
          ['done', { steps: 2 }],
        ],
        [['done', { steps: 1 }]],
      ],
      { path: '/search' },
    );
    await askFromPalette(user, 'assign the pricing task to Ana');
    const panel = await screen.findByRole('complementary', { name: 'Ask Mo' });
    const asks = await within(panel).findByRole('region', { name: 'Mo asks (AI)' });
    expect(within(panel).getByText('Previewed update task (failed)')).toBeInTheDocument();
    await user.click(within(asks).getByRole('button', { name: /T-13 Draft pricing FAQ/ }));
    await waitFor(() => expect(cmd.requests).toHaveLength(2));
    expect(cmd.requests[0]!.screen).toEqual({ kind: 'search' });
    expect(cmd.requests[1]!.text).toBe('assign the pricing task to Ana (I mean T-13)');
  });

  it('Edit puts the request back into ⌘K', async () => {
    const { user } = await boot([J7]);
    await askFromPalette(user, 'assign all overdue tasks in Website Revamp to Ana');
    const card = await screen.findByRole('region', { name: 'Mo suggests (AI)' });
    await user.click(within(card).getByRole('button', { name: 'Edit' }));
    const palette = await screen.findByRole('dialog', { name: 'Command palette' });
    expect(within(palette).getByRole('combobox')).toHaveValue(
      'assign all overdue tasks in Website Revamp to Ana',
    );
  });

  it('shows errors from the stream', async () => {
    const { user } = await boot([
      [['error', { reason: 'timeout', message: 'Mo is unavailable right now. Try again shortly.' }]],
    ]);
    await askFromPalette(user, 'assign all overdue tasks to Ana');
    expect(await screen.findByRole('alert')).toHaveTextContent('Mo is unavailable right now');
  });

  it('searches stay searches, and there is no Mo option with AI off', async () => {
    const { user } = await boot([], { aiEnabled: false });
    await user.keyboard('{Control>}k{/Control}');
    const palette = await screen.findByRole('dialog', { name: 'Command palette' });
    await user.type(within(palette).getByRole('combobox'), 'assign all overdue tasks to Ana');
    expect(within(palette).queryByRole('option', { name: /Ask Mo to do this/ })).toBeNull();
  });

  it('the auto-apply preference is a setting on /settings/ai', async () => {
    const { user, cmd } = await boot([], { path: '/settings/ai' });
    const box = await screen.findByRole('checkbox', {
      name: /Apply low-risk changes from Mo without asking/,
    });
    expect(box).not.toBeChecked();
    await user.click(box);
    await waitFor(() => expect(cmd.saved).toEqual([{ auto_apply_low_risk: true }]));
  });
});

describe('looksLikeInstruction', () => {
  it.each([
    ['assign all overdue tasks in Website Revamp to Ana', true],
    ['move the pricing task to Review', true],
    ['please mark T-12 as done', true],
    ['give the launch tasks to me', true],
    ['pricing copy', false],
    ['website revamp', false],
    ['how to write good copy', false],
    ['assign', false],
  ])('%s → %s', (q, want) => expect(looksLikeInstruction(q)).toBe(want));
});
