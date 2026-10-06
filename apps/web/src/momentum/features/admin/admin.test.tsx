import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { membersHandlers } from '@/mocks/members';
import { notificationHandlers } from '@/mocks/notifications';
import { projectHandlers } from '@/mocks/projects';
import { teamHandlers } from '@/mocks/teams';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

const job = (status: string, attempts: number) => ({
  id: 7,
  task_name: 'momentum:index_embeddings',
  queue_name: 'momentum_ai',
  status,
  attempts,
  scheduled_at: null,
  last_event_at: '2026-10-06T08:00:00Z',
});
const entry = (id: string, over: Record<string, unknown>) => ({
  id,
  created_at: '2026-10-06T08:00:00Z',
  actor_id: null,
  actor_name: null,
  actor_kind: 'user',
  verb: 'task.updated',
  entity_type: 'task',
  entity_id: `t-${id}`,
  entity_label: null,
  changes: [],
  undone: false,
  ...over,
});

function boot(path: string) {
  let status = 'failed';
  server.use(
    ...authHandlers({ loggedIn: true, me: { role: 'admin' } }).handlers,
    ...teamHandlers(),
    ...projectHandlers(),
    ...notificationHandlers(),
    ...membersHandlers(),
    http.get('*/api/v1/admin/jobs', () =>
      HttpResponse.json({
        counts: { failed: status === 'failed' ? 1 : 0, todo: status === 'todo' ? 1 : 0 },
        jobs: status === 'failed' ? [job('failed', 3)] : [],
      }),
    ),
    http.post('*/api/v1/admin/jobs/7/retry', () => {
      status = 'todo';
      return HttpResponse.json(job('todo', 4));
    }),
    http.get('*/api/v1/admin/activity', () =>
      HttpResponse.json({
        data: [
          entry('a1', {
            actor_id: 'u1',
            actor_name: 'Ravi Kumar',
            entity_label: 'Ship it',
            changes: ['assignee_id'],
          }),
          entry('a2', { actor_kind: 'agent', verb: 'task.created' }),
        ],
        meta: { next_cursor: null },
      }),
    ),
  );
  window.history.replaceState(null, '', path);
  render(<MomentumApp />);
  return userEvent.setup();
}

describe('Admin operations (S7.5.4)', () => {
  it('shows failed background jobs and retries one', async () => {
    const user = boot('/settings/jobs');
    await screen.findByRole('heading', { name: 'Background jobs' });
    expect(await screen.findByText('index_embeddings')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Retry momentum:index_embeddings/ }));
    expect(await screen.findByText('No failed jobs')).toBeInTheDocument();
  });

  it('lists the audit trail without naming what the admin can not see', async () => {
    boot('/settings/audit');
    await screen.findByRole('heading', { name: 'Audit trail' });
    const rows = await screen.findAllByRole('row');
    expect(within(rows[1]!).getByText('Ship it')).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/assignee_id/)).toBeInTheDocument();
    expect(within(rows[2]!).getByText(/a task you can.t see/)).toBeInTheDocument();
    expect(within(rows[2]!).getByText('(agent)')).toBeInTheDocument();
  });
});
