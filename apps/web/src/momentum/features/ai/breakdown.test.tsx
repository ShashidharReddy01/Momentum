import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { aiActionFixture, aiHandlers } from '@/mocks/ai';
import { authHandlers } from '@/mocks/handlers';
import { multiHomingHandlers } from '@/mocks/multiHoming';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const ACTION = aiActionFixture({
  id: 'act-b',
  source: 'inline',
  summary: 'Break T-1 into 3 subtasks',
  operations: [
    {
      tool: 'create_subtasks',
      args: {},
      summary: 'Would create 3 subtask(s) under T-1',
      risk: 'low',
      diff: [
        {
          entity_type: 'task',
          entity_id: 'new-1',
          label: 'Collect prices',
          verb: 'task.created',
          changes: { title: [null, 'Collect prices'] },
          display: { title: [null, 'Collect prices'] },
        },
      ],
    },
  ],
});

function boot(opts: { role?: string; aiEnabled?: boolean; fail?: boolean } = {}) {
  const requests: unknown[] = [];
  const ai = aiHandlers([ACTION]);
  server.use(
    ...authHandlers({ loggedIn: true, config: { ai_enabled: opts.aiEnabled ?? true } }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: opts.role ?? 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...multiHomingHandlers(
      '',
      [{ id: 'seed-1', name: 'Website Revamp', color: null }],
      [{ task_id: 'task-1', project_id: 'seed-1', section_id: 'sec-1', position: '100000' }],
    ),
    ...ai.handlers,
  );
  server.use(
    http.post('*/api/v1/ai/tasks/:id/subtasks', async ({ request, params }) => {
      requests.push({ id: params.id, body: await request.json() });
      if (opts.fail)
        return HttpResponse.json(
          { code: 'ai_unavailable', title: 'AI is temporarily unavailable', status: 503 },
          { status: 503, headers: { 'content-type': 'application/problem+json' } },
        );
      return HttpResponse.json({
        action_id: 'act-b',
        notes: ["“Check with Tom”: Tom Becker isn't someone on this project, so it's unassigned."],
        count: 3,
      });
    }),
  );
  window.history.replaceState(null, '', '/projects/seed-1?task=task-1');
  render(<MomentumApp />);
  return { requests, ai, user: userEvent.setup() };
}

const pane = () => screen.findByRole('complementary', { name: 'Task details' });

describe('Break into subtasks (S3.4.2)', () => {
  it('asks with optional guidance, shows notes and a PreviewCard to apply', async () => {
    const { user, requests, ai } = boot();
    const p = await pane();
    await user.click(await within(p).findByRole('button', { name: /Break down/ }));
    await user.type(within(p).getByRole('textbox', { name: 'Guidance for Mo (optional)' }), 'by week');
    await user.click(within(p).getByRole('button', { name: 'Suggest subtasks' }));
    const notes = await within(p).findByRole('list', { name: 'Mo adjusted' });
    expect(notes).toHaveTextContent("Tom Becker isn't someone on this project");
    const card = await within(p).findByRole('region', { name: 'Mo suggests (AI)' });
    expect(card).toHaveTextContent('Collect prices');
    await user.click(within(card).getByRole('button', { name: 'Apply' }));
    expect(await within(card).findByText('Applied')).toBeInTheDocument();
    expect(requests).toEqual([{ id: 'task-1', body: { hint: 'by week' } }]);
    expect(ai.calls.map((c) => c.path)).toEqual(['apply']);
  });

  it('sends no guidance when left empty; an outage is reported', async () => {
    const { user, requests } = boot({ fail: true });
    const p = await pane();
    await user.click(await within(p).findByRole('button', { name: /Break down/ }));
    await user.click(within(p).getByRole('button', { name: 'Suggest subtasks' }));
    await waitFor(() => expect(within(p).getByRole('alert')).toHaveTextContent('Mo is unavailable'));
    expect(requests).toEqual([{ id: 'task-1', body: { hint: null } }]);
  });

  it('not offered to viewers, or while AI is off', async () => {
    boot({ role: 'viewer' });
    const p = await pane();
    await within(p).findByRole('list', { name: 'Subtasks' });
    expect(within(p).queryByRole('button', { name: /Break down/ })).toBeNull();
  });

  it('not offered while AI is off', async () => {
    boot({ aiEnabled: false });
    const p = await pane();
    await within(p).findByRole('list', { name: 'Subtasks' });
    expect(within(p).queryByRole('button', { name: /Break down/ })).toBeNull();
  });
});
