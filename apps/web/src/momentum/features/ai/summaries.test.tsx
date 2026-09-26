import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { multiHomingHandlers } from '@/mocks/multiHoming';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { sectionHandlers } from '@/mocks/sections';
import { taskHandlers } from '@/mocks/tasks';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const ME = '01a0ccaf-8f68-77d2-a888-584ea1e80ea8';
const comment = (id: string, text: string, at: string) => ({
  kind: 'comment',
  at,
  comment: {
    id,
    task_id: 'task-1',
    author_id: ME,
    body: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] },
    is_ai: false,
    created_at: at,
    edited_at: null,
    reactions: [],
    can_edit: true,
    can_delete: true,
  },
});

function boot(
  opts: { comments?: number; aiEnabled?: boolean; summarize?: (body: unknown) => Response } = {},
) {
  const calls: unknown[] = [];
  const feed = [
    comment('c-1', 'Proposal: three tiers', '2026-09-22T10:00:00Z'),
    comment('c-2', 'Agreed', '2026-09-23T10:00:00Z'),
  ].slice(0, opts.comments ?? 2);
  server.use(
    ...authHandlers({ loggedIn: true, config: { ai_enabled: opts.aiEnabled ?? true } }).handlers,
    ...teamHandlers(),
    ...projectHandlers('', undefined, [{ name: 'Website Revamp', my_role: 'admin' }]),
    ...sectionHandlers('', { 'seed-1': ['Backlog'] }),
    ...taskHandlers('', { 'seed-1': { 'sec-1': ['First'] } }),
    ...multiHomingHandlers(
      '',
      [{ id: 'seed-1', name: 'Website Revamp', color: null }],
      [{ task_id: 'task-1', project_id: 'seed-1', section_id: 'sec-1', position: '100000' }],
    ),
    ...notificationHandlers('', [
      {
        id: 'n-1',
        kind: 'assigned',
        entity_type: 'task',
        entity_id: 'task-1',
        activity_id: null,
        title: 'You were assigned "First"',
        snippet: null,
        read_at: null,
        archived_at: null,
        created_at: new Date().toISOString(),
      },
    ]),
  );
  server.use(
    http.get('*/api/v1/tasks/:id/feed', () => HttpResponse.json({ data: feed, truncated: false })),
    http.post('*/api/v1/ai/summarize', async ({ request }) => {
      const body = await request.json();
      calls.push(body);
      if (opts.summarize) return opts.summarize(body);
      const inbox = (body as { target: string }).target === 'inbox';
      return HttpResponse.json(
        inbox
          ? {
              summary: '- You were assigned [T-1].',
              citations: [
                { ref: '[T-1]', type: 'task', valid: true, id: 'task-1', key: 'T-1', title: 'First' },
              ],
              cached: false,
              count: 1,
              omitted: 0,
              created_at: '2026-09-26T10:00:00Z',
            }
          : {
              summary: '- Ravi proposed three tiers [C1]; agreed [C2]. See [C7].',
              citations: [
                {
                  ref: '[C1]',
                  type: 'comment',
                  valid: true,
                  id: 'c-1',
                  title: 'Ravi Kumar',
                  created_at: '2026-09-22T10:00:00Z',
                },
                {
                  ref: '[C2]',
                  type: 'comment',
                  valid: true,
                  id: 'c-2',
                  title: 'Ravi Kumar',
                  created_at: '2026-09-23T10:00:00Z',
                },
                { ref: '[C7]', type: 'comment', valid: false, id: null, title: null, created_at: null },
              ],
              cached: false,
              count: 2,
              omitted: 0,
              created_at: '2026-09-26T10:00:00Z',
            },
      );
    }),
  );
  return { calls, user: userEvent.setup() };
}

async function openPane(path = '/projects/seed-1?task=task-1') {
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return screen.findByRole('complementary', { name: 'Task details' });
}

describe('Summaries (S3.4.1)', () => {
  it('summarizes a task thread with comment citations; hide dismisses it', async () => {
    const { user, calls } = boot();
    const pane = await openPane();
    const activity = await within(pane).findByRole('region', { name: 'Comments and activity' });
    await user.click(await within(activity).findByRole('button', { name: /Summarize/ }));
    const callout = await within(activity).findByRole('region', { name: 'Mo’s summary (AI)' });
    expect(within(callout).getByLabelText(/^Comment by Ravi Kumar, Sep 22/)).toHaveTextContent(
      'Ravi · Sep 22',
    );
    expect(within(callout).getByText('[C7]')).toHaveAttribute(
      'title',
      "Mo cited a comment that isn't in this thread",
    );
    expect(within(callout).getByText('From 2 comments.')).toBeInTheDocument();
    expect(calls).toEqual([{ target: 'task_thread', task_id: 'task-1' }]);
    await user.click(within(callout).getByRole('button', { name: 'Hide summary' }));
    expect(within(activity).queryByRole('region', { name: 'Mo’s summary (AI)' })).toBeNull();
  });

  it('no Summarize for a single comment, or while AI is off', async () => {
    boot({ comments: 1 });
    const pane = await openPane();
    await within(pane).findByText('Proposal: three tiers');
    expect(within(pane).queryByRole('button', { name: /Summarize/ })).toBeNull();
  });

  it('AI off: no summary buttons', async () => {
    boot({ aiEnabled: false });
    const pane = await openPane();
    await within(pane).findByText('Agreed');
    expect(within(pane).queryByRole('button', { name: /Summarize/ })).toBeNull();
  });

  it('inbox catch-up links the tasks it mentions; an outage says so', async () => {
    const { user, calls } = boot();
    window.history.replaceState(null, '', '/inbox');
    render(<MomentumApp />);
    await screen.findByText('You were assigned "First"');
    await user.click(screen.getByRole('button', { name: /Catch me up/ }));
    const callout = await screen.findByRole('region', { name: 'Mo’s catch-up (AI)' });
    expect(within(callout).getByRole('link', { name: 'T-1 First' })).toHaveAttribute('href', '/task/task-1');
    expect(calls).toEqual([{ target: 'inbox' }]);
  });

  it('shows an unavailable message when the gateway is down', async () => {
    const { user } = boot({
      summarize: () =>
        HttpResponse.json(
          { code: 'ai_unavailable', title: 'AI is temporarily unavailable', status: 503, reason: 'timeout' },
          { status: 503, headers: { 'content-type': 'application/problem+json' } },
        ),
    });
    const pane = await openPane();
    await user.click(await within(pane).findByRole('button', { name: /Summarize/ }));
    await waitFor(() =>
      expect(within(pane).getByRole('alert')).toHaveTextContent(
        'Mo is unavailable right now. Try again shortly.',
      ),
    );
  });
});
