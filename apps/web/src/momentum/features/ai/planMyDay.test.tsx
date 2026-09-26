import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiActionFixture, aiHandlers } from '@/mocks/ai';
import { authHandlers } from '@/mocks/handlers';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const T1 = { ref: '[T-1]', type: 'task', valid: true, id: 'task-1', key: 'T-1', title: 'Alpha' };
const ACTION = aiActionFixture({
  id: 'act-p',
  source: 'inline',
  summary: 'Plan my day: 2 for today',
  operations: [
    {
      tool: 'plan_my_day',
      args: {},
      summary: 'Would plan your day: 2 for today, 0 to later',
      risk: 'low',
      diff: [
        {
          entity_type: 'my_task',
          entity_id: 'task-1',
          label: 'T-1 Alpha',
          verb: 'my_task.moved',
          changes: { bucket: ['recently_assigned', 'today'] },
          display: { bucket: ['recently_assigned', 'today'] },
        },
      ],
    },
  ],
});

function boot(plan: object | null, opts: { aiEnabled?: boolean } = {}) {
  const ai = aiHandlers([ACTION]);
  let calls = 0;
  server.use(
    ...authHandlers({ loggedIn: true, config: { ai_enabled: opts.aiEnabled ?? true } }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['Alpha', 'Bravo'] } }, 15, ['Alpha', 'Bravo']),
    ...ai.handlers,
    http.post('*/api/v1/ai/plan-my-day', () => {
      calls += 1;
      return plan
        ? HttpResponse.json(plan)
        : HttpResponse.json(
            {
              code: 'validation_failed',
              title: 'Invalid',
              status: 422,
              detail: 'You have no open tasks to plan',
            },
            { status: 422, headers: { 'content-type': 'application/problem+json' } },
          );
    }),
  );
  window.history.replaceState(null, '', '/my-tasks');
  render(<MomentumApp />);
  return { ai, calls: () => calls, user: userEvent.setup() };
}

describe('Plan my day (S3.4.5)', () => {
  it('shows the reasons, notes and a PreviewCard that applies the plan', async () => {
    const { user, ai } = boot({
      action_id: 'act-p',
      rationale: 'Start with [T-1]: it is overdue.',
      today: ['T-1', 'T-2'],
      later: [],
      notes: ["Left out T-9: it isn't one of your open tasks."],
      citations: [T1],
    });
    await user.click(await screen.findByRole('button', { name: /Plan my day/ }));
    const plan = await screen.findByRole('region', { name: 'Mo’s plan (AI)' });
    expect(within(plan).getByRole('link', { name: 'T-1 Alpha' })).toBeInTheDocument();
    expect(within(plan).getByRole('list', { name: 'Mo adjusted' })).toHaveTextContent('Left out T-9');
    const card = await screen.findByRole('region', { name: 'Mo suggests (AI)' });
    await user.click(within(card).getByRole('button', { name: 'Apply' }));
    expect(await within(card).findByText('Applied')).toBeInTheDocument();
    expect(ai.calls.map((c) => c.path)).toEqual(['apply']);
  });

  it('says so when the day already matches, and shows errors', async () => {
    const { user } = boot({
      action_id: null,
      rationale: '',
      today: ['T-1'],
      later: [],
      notes: [],
      citations: [],
    });
    await user.click(await screen.findByRole('button', { name: /Plan my day/ }));
    expect(await screen.findByText('Your day already matches this plan.')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Mo suggests (AI)' })).toBeNull();
  });

  it('reports a server refusal', async () => {
    const { user } = boot(null);
    await user.click(await screen.findByRole('button', { name: /Plan my day/ }));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('You have no open tasks to plan'),
    );
  });

  it('not offered while AI is off', async () => {
    boot(null, { aiEnabled: false });
    await screen.findByRole('listitem', { name: 'Alpha' });
    expect(screen.queryByRole('button', { name: /Plan my day/ })).toBeNull();
  });
});
