import { render, screen, waitFor } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
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

function at(path: string) {
  window.history.replaceState(null, '', path);
}

describe('Realtime, wired into the app shell', () => {
  it('connects once signed in when the server has the feature on, and shows/hides the reconnecting banner', async () => {
    server.use(...authHandlers({ loggedIn: true, config: { features: { realtime: true } } }).handlers);
    // A still-static Phase-3 placeholder route, chosen so this realtime-focused test doesn't
    // need to mock teams/projects/notifications just to render the shell (the same reason
    // /inbox was originally picked, before S2.5 made it a real, data-fetching page).
    at('/ask');
    render(<MomentumApp />);
    await screen.findByText(/Ask Mo arrives in Phase 3/);

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

  it('never opens a websocket when the server has the feature off', async () => {
    server.use(...authHandlers({ loggedIn: true, config: { features: { realtime: false } } }).handlers);
    at('/ask');
    render(<MomentumApp />);
    await screen.findByText(/Ask Mo arrives in Phase 3/);
    expect(MockWebSocket.instances).toHaveLength(0);
  });
});
