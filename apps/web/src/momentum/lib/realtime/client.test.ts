import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RealtimeClient } from './client';
import { MockWebSocket } from './mockWebSocket';

beforeEach(() => {
  MockWebSocket.reset();
  vi.stubGlobal('WebSocket', MockWebSocket);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function makeClient(onUnauthenticated = () => {}) {
  return new RealtimeClient('ws://test/ws', onUnauthenticated);
}

describe('RealtimeClient', () => {
  it('a subscribe made before the socket opens is sent once it opens; after open, immediately', () => {
    const client = makeClient();
    const states: string[] = [];
    client.onStateChange((s) => states.push(s));
    client.connect();
    expect(states).toEqual(['connecting']);

    const unsubscribe = client.subscribe('project:1', () => {});
    expect(MockWebSocket.latest().sent).toEqual([]); // not yet open: nothing sent yet
    MockWebSocket.latest().open();
    expect(states).toEqual(['connecting', 'open']);
    expect(MockWebSocket.latest().sent).toContainEqual({
      op: 'subscribe',
      channel: 'project:1',
      since: undefined,
    });

    client.subscribe('task:2', () => {}); // made after open: sent right away, no waiting for onopen
    expect(MockWebSocket.latest().sent).toContainEqual({ op: 'subscribe', channel: 'task:2' });

    unsubscribe();
    expect(MockWebSocket.latest().sent).toContainEqual({ op: 'unsubscribe', channel: 'project:1' });
  });

  it('routes an event to only the listeners on its labeled channel', () => {
    const client = makeClient();
    client.connect();
    MockWebSocket.latest().open();
    const onProject = vi.fn();
    const onTask = vi.fn();
    client.subscribe('project:1', onProject);
    client.subscribe('task:2', onTask);

    MockWebSocket.latest().push({
      type: 'event',
      id: 5,
      event: 'task.updated',
      entity_type: 'task',
      entity_id: '2',
      channel: 'project:1',
      data: {},
      actor: null,
      request_id: null,
      activity_id: null,
    });
    expect(onProject).toHaveBeenCalledTimes(1);
    expect(onTask).not.toHaveBeenCalled();
  });

  it('shares one wire subscription across multiple listeners on the same channel (ref-counted)', () => {
    const client = makeClient();
    client.connect();
    MockWebSocket.latest().open();
    const a = vi.fn();
    const b = vi.fn();
    const unsubA = client.subscribe('project:1', a);
    client.subscribe('project:1', b);
    const subscribeMessages = MockWebSocket.latest().sent.filter(
      (m) => (m as { op?: string }).op === 'subscribe',
    );
    expect(subscribeMessages).toHaveLength(1); // not sent twice for the second listener

    MockWebSocket.latest().push({
      type: 'event',
      id: 1,
      event: 'task.updated',
      entity_type: 'task',
      entity_id: 't',
      channel: 'project:1',
      data: {},
      actor: null,
      request_id: null,
      activity_id: null,
    });
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);

    unsubA();
    // b still wants it: no unsubscribe sent yet
    expect(
      MockWebSocket.latest().sent.filter((m) => (m as { op?: string }).op === 'unsubscribe'),
    ).toHaveLength(0);
  });

  it('replies to server pings', () => {
    const client = makeClient();
    client.connect();
    MockWebSocket.latest().open();
    MockWebSocket.latest().push({ type: 'ping' });
    expect(MockWebSocket.latest().sent).toContainEqual({ op: 'pong' });
  });

  it('reconnects on an unexpected close and re-subscribes with the last seen id (replay)', () => {
    vi.useFakeTimers();
    const client = makeClient();
    const states: string[] = [];
    client.onStateChange((s) => states.push(s));
    client.connect();
    MockWebSocket.latest().open();
    client.subscribe('project:1', () => {});
    MockWebSocket.latest().push({
      type: 'event',
      id: 42,
      event: 'task.updated',
      entity_type: 'task',
      entity_id: 't',
      channel: 'project:1',
      data: {},
      actor: null,
      request_id: null,
      activity_id: null,
    });

    MockWebSocket.latest().close(1006); // an unexpected drop, not our own close()
    expect(states.at(-1)).toBe('reconnecting');
    vi.runOnlyPendingTimers();
    expect(MockWebSocket.instances).toHaveLength(2); // a new socket was opened
    MockWebSocket.latest().open();
    expect(states.at(-1)).toBe('open');
    expect(MockWebSocket.latest().sent).toContainEqual({ op: 'subscribe', channel: 'project:1', since: 42 });
  });

  it('a 4401 close calls onUnauthenticated and does not reconnect', () => {
    vi.useFakeTimers();
    const onUnauthenticated = vi.fn();
    const client = makeClient(onUnauthenticated);
    client.connect();
    MockWebSocket.latest().open();
    MockWebSocket.latest().close(4401);
    expect(onUnauthenticated).toHaveBeenCalledTimes(1);
    vi.runAllTimers();
    expect(MockWebSocket.instances).toHaveLength(1); // no reconnect attempt
  });

  it('close() is final: no reconnect, state becomes closed', () => {
    vi.useFakeTimers();
    const client = makeClient();
    client.connect();
    MockWebSocket.latest().open();
    client.close();
    const states: string[] = [];
    client.onStateChange((s) => states.push(s));
    expect(states).toEqual(['closed']);
    vi.runAllTimers();
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("a resync message drops that channel's cursor so the next reconnect starts live", () => {
    vi.useFakeTimers();
    const client = makeClient();
    client.connect();
    MockWebSocket.latest().open();
    client.subscribe('project:1', () => {});
    MockWebSocket.latest().push({
      type: 'event',
      id: 7,
      event: 'task.updated',
      entity_type: 'task',
      entity_id: 't',
      channel: 'project:1',
      data: {},
      actor: null,
      request_id: null,
      activity_id: null,
    });
    MockWebSocket.latest().push({ type: 'resync', channel: 'project:1' });
    MockWebSocket.latest().close(1006);
    vi.runOnlyPendingTimers();
    MockWebSocket.latest().open();
    // since is omitted (undefined), not the stale id=7 — resync cleared the cursor
    const sub = MockWebSocket.latest().sent.find((m) => (m as { op?: string }).op === 'subscribe');
    expect(sub).toEqual({ op: 'subscribe', channel: 'project:1', since: undefined });
  });
});
