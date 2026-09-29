import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiActionFixture, aiHandlers } from '@/mocks/ai';
import { agentFixture, agentHandlers, runFixture } from '@/mocks/agents';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function boot(
  path: string,
  agents: ReturnType<typeof agentHandlers>,
  extra: Parameters<typeof server.use> = [],
) {
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...agents.handlers,
    ...extra,
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Agent runs (S5.1.3)', () => {
  it('explains a run: why, each step, the answer, cost, and what waits for you', async () => {
    const action = aiActionFixture({ id: 'act-1' });
    const ai = aiHandlers([action]);
    const run = runFixture({
      actions: [
        {
          id: 'act-1',
          summary: 'Would set priority high',
          state: 'proposed',
          risk: 'low',
          proposed_for: { id: 'u-1', name: 'Ravi Kumar' },
          mine: true,
        },
      ],
    });
    boot('/agents/runs/run-1', agentHandlers({ run }), ai.handlers);

    expect(await screen.findByRole('heading', { name: 'Run · Assigned a task' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Teammate/ })).toHaveAttribute('href', '/agents/agent-1');
    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'T-12 Research competitor pricing' })).toHaveAttribute(
      'href',
      '/task/t-1',
    );
    expect(screen.getByText(/1,500 tokens · <\$0\.01/)).toBeInTheDocument();
    const steps = screen.getByRole('region', { name: 'Steps' });
    expect(within(steps).getByText('search_tasks')).toBeInTheDocument();
    expect(within(steps).getByText('Found 3 tasks')).toBeInTheDocument();
    // AI-authored answer carries the amber AI marking
    expect(screen.getByRole('region', { name: 'Teammate answered (AI)' })).toHaveTextContent(
      'three competitors',
    );
    // the proposal waiting for me is decidable right here
    const waiting = screen.getByRole('region', { name: 'Waiting for you' });
    expect(await within(waiting).findByRole('button', { name: 'Apply' })).toBeInTheDocument();
  });

  it('hides step details from someone the run was not for', async () => {
    const run = runFixture({
      detail: 'summary',
      answer: null,
      trace: [
        { at: '2026-09-28T10:00:05Z', kind: 'trigger', summary: 'event trigger', name: null, ok: null },
        { at: '2026-09-28T10:00:09Z', kind: 'tool', summary: '', name: 'search_tasks', ok: true },
      ],
    });
    boot('/agents/runs/run-1', agentHandlers({ run }));
    expect(await screen.findByText(/step details are shown only to admins/)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /answered/ })).toBeNull();
    expect(screen.getByText('search_tasks')).toBeInTheDocument();
  });

  it('shows a failed run’s error plainly', async () => {
    const run = runFixture({
      status: 'budget_exceeded',
      error: 'Teammate has used $5.00 of its $5.00 monthly budget.',
      answer: null,
    });
    boot('/agents/runs/run-1', agentHandlers({ run }));
    expect(await screen.findByRole('alert')).toHaveTextContent('monthly budget');
    expect(screen.getByText('Budget used up')).toBeInTheDocument();
  });

  it('lists an agent’s runs with status and trigger filters', async () => {
    const ok = runFixture();
    const failed = runFixture({
      id: 'run-2',
      status: 'failed',
      trigger: 'mentioned',
      error: 'No access',
      task: null,
    });
    const agents = agentHandlers({ agent: agentFixture(), runs: [ok, failed] });
    const user = boot('/agents/agent-1', agents);
    expect(await screen.findByRole('heading', { name: 'Teammate' })).toBeInTheDocument();
    expect(
      screen.getByText(/Asks before changing · budget \$5\.00\/month · works in Website Revamp/),
    ).toBeInTheDocument();
    const list = await screen.findByRole('list', { name: 'Runs' });
    expect(within(list).getAllByRole('link')).toHaveLength(2);
    expect(within(list).getAllByRole('link')[0]).toHaveAttribute('href', '/agents/runs/run-1');

    await user.selectOptions(screen.getByLabelText('Status'), 'failed');
    expect(await screen.findByText(/No access/)).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Runs' })).getAllByRole('link')).toHaveLength(1);
    expect(agents.queries.at(-1)?.get('status')).toBe('failed');

    await user.selectOptions(screen.getByLabelText('Trigger'), 'schedule');
    expect(await screen.findByText('No runs match these filters.')).toBeInTheDocument();
  });
});
