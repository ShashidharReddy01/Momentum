import { http, HttpResponse } from 'msw';
import { render, screen, waitFor } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { ravi } from '@/mocks/fixtures';
import { authHandlers } from '@/mocks/handlers';
import { MockWebSocket } from './mockWebSocket';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  MockWebSocket.reset();
  vi.stubGlobal('WebSocket', MockWebSocket);
});
afterEach(() => {
  server.resetHandlers();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});
afterAll(() => server.close());

const noConversations = [
  http.get('*/api/v1/ai/conversations', () => HttpResponse.json({ data: [], meta: { next_cursor: null } })),
];

function at(path: string) {
  window.history.replaceState(null, '', path);
}

describe('Realtime, wired into the app shell', () => {
  it('connects once signed in when the server has the feature on, and shows/hides the reconnecting banner', async () => {
    server.use(
      ...authHandlers({ loggedIn: true, config: { features: { realtime: true } } }).handlers,
      ...noConversations,
    );
    // Ask Mo's page, chosen so this realtime-focused test doesn't need to mock
    // teams/projects/notifications just to render the shell (it only lists conversations).
    at('/ask');
    render(<MomentumApp />);
    await screen.findByText('Ask Mo about your work');

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
    expect(MockWebSocket.latest().url).toMatch(/\/ws$/);
    expect(screen.queryByText('Reconnecting…')).toBeNull();

    MockWebSocket.latest().open();
    expect(screen.queryByText('Reconnecting…')).toBeNull(); // a healthy connection: no banner

    MockWebSocket.latest().close(1006); // an unexpected drop
    expect(await screen.findByText('Reconnecting…')).toBeInTheDocument();

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(2));
    MockWebSocket.latest().open();
    await waitFor(() => expect(screen.queryByText('Reconnecting…')).toBeNull());
  });

  it('keeps the inbox and the bell live on the inbox page itself (S5.0.1)', async () => {
    // before S5.0.1 only Home and My Tasks subscribed to user:<me>, so a notification created
    // while /inbox was open never appeared without a reload
    const rows: Record<string, unknown>[] = [];
    server.use(
      ...authHandlers({ loggedIn: true, config: { features: { realtime: true } } }).handlers,
      ...noConversations,
      http.get('*/api/v1/notifications', () =>
        HttpResponse.json({ data: rows, meta: { next_cursor: null } }),
      ),
      http.get('*/api/v1/notifications/unread-count', () => HttpResponse.json({ count: rows.length })),
      ...['teams', 'projects', 'favorites', 'users'].map((path) =>
        http.get(`*/api/v1/${path}`, () => HttpResponse.json({ data: [], meta: { next_cursor: null } })),
      ),
    );
    at('/inbox');
    render(<MomentumApp />);
    expect(await screen.findByText("You're all caught up")).toBeInTheDocument();
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
    const ws = MockWebSocket.latest();
    ws.open();
    const channel = `user:${ravi.id}`; // the signed-in fixture user
    await waitFor(() => expect(ws.sent).toContainEqual({ op: 'subscribe', channel }));

    rows.push({
      id: 'n-1',
      kind: 'agent_proposal',
      entity_type: 'task',
      entity_id: 't-1',
      activity_id: null,
      title: 'Helper suggests: raise the priority',
      snippet: null,
      actor: null,
      read_at: null,
      archived_at: null,
      created_at: new Date().toISOString(),
    });
    ws.push({
      type: 'event',
      id: 1,
      event: 'notification.created',
      entity_type: 'notification',
      entity_id: 'n-1',
      channel,
      data: {},
      actor: null,
      request_id: null,
      activity_id: null,
    });
    expect(await screen.findByText('Helper suggests: raise the priority')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Notifications (1 unread)' })).toBeInTheDocument();
  });

  it('never opens a websocket when the server has the feature off', async () => {
    server.use(
      ...authHandlers({ loggedIn: true, config: { features: { realtime: false } } }).handlers,
      ...noConversations,
    );
    at('/ask');
    render(<MomentumApp />);
    await screen.findByText('Ask Mo about your work');
    expect(MockWebSocket.instances).toHaveLength(0);
  });
});
