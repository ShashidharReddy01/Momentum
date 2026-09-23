import type { ClientMessage, ConnectionState, RealtimeEvent, ServerMessage } from './types';

const JITTER_CAP_MS = 5_000; // spread reconnect attempts across clients after a shared outage
const BACKOFF_MS = [500, 1000, 2000, 5000, 10000, 20000, 30000];

type Listener = (event: RealtimeEvent) => void;
type StateListener = (state: ConnectionState) => void;

interface ChannelState {
  refCount: number;
  listeners: Set<Listener>;
  lastEventId: number | null;
}

/**
 * One websocket connection to `/ws`, shared by every `useChannel` call in the app (see
 * RealtimeProvider). Handles reconnect with backoff, re-subscribing every wanted channel on
 * reconnect (replaying from the last id it saw on that channel), and per-channel dispatch.
 *
 * Not exported for direct use outside this module + RealtimeProvider — components use the
 * `useChannel` hook instead.
 */
export class RealtimeClient {
  private ws: WebSocket | null = null;
  private channels = new Map<string, ChannelState>();
  private stateListeners = new Set<StateListener>();
  private state: ConnectionState = 'connecting';
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(
    private readonly url: string,
    /** Called on an unrecoverable auth failure (close code 4401): the app should treat this
     * like any other expired-session signal. */
    private readonly onUnauthenticated: () => void,
  ) {}

  connect(): void {
    if (this.closed || this.ws) return;
    this.setState(this.attempt === 0 ? 'connecting' : 'reconnecting');
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.setState('open');
      // re-subscribe everything, replaying each channel from the last id we saw on it (omitted
      // on a first-ever connect: a fresh page load already has current data via REST)
      for (const [channel, ch] of this.channels) {
        this.send({ op: 'subscribe', channel, since: ch.lastEventId ?? undefined });
      }
    };
    ws.onmessage = (e) => {
      let msg: ServerMessage;
      try {
        msg = JSON.parse(e.data as string) as ServerMessage;
      } catch {
        return;
      }
      this.handleMessage(msg);
    };
    ws.onclose = (e) => {
      this.ws = null;
      if (e.code === 4401) {
        this.onUnauthenticated();
        return; // don't reconnect into a dead session
      }
      if (this.closed) return;
      this.setState('reconnecting');
      this.scheduleReconnect();
    };
    ws.onerror = () => ws.close();
  }

  close(): void {
    this.closed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
    this.setState('closed');
  }

  onStateChange(fn: StateListener): () => void {
    this.stateListeners.add(fn);
    fn(this.state);
    return () => void this.stateListeners.delete(fn);
  }

  /** Subscribe to a channel; ref-counted, so N callers watching the same channel share one
   * wire subscription. Returns an unsubscribe function. */
  subscribe(channel: string, onEvent: Listener): () => void {
    let ch = this.channels.get(channel);
    if (!ch) {
      ch = { refCount: 0, listeners: new Set(), lastEventId: null };
      this.channels.set(channel, ch);
    }
    ch.refCount += 1;
    ch.listeners.add(onEvent);
    if (ch.refCount === 1 && this.state === 'open') {
      this.send({ op: 'subscribe', channel });
    }
    return () => {
      const c = this.channels.get(channel);
      if (!c) return;
      c.listeners.delete(onEvent);
      c.refCount -= 1;
      if (c.refCount <= 0) {
        this.channels.delete(channel);
        if (this.state === 'open') this.send({ op: 'unsubscribe', channel });
      }
    };
  }

  private handleMessage(msg: ServerMessage): void {
    switch (msg.type) {
      case 'ping':
        this.send({ op: 'pong' });
        return;
      case 'event':
        this.deliver(msg);
        return;
      case 'resync': {
        // the backlog for this channel was too large to replay: forget our cursor so a
        // future reconnect starts live instead of retrying a doomed huge replay, and let
        // listeners know so they can refetch (they already have a REST query to do that)
        const ch = this.channels.get(msg.channel);
        if (ch) ch.lastEventId = null;
        return;
      }
      case 'overflow':
        // this connection fell behind and the server dropped some queued messages: every
        // channel we're watching might have a gap, so drop every cursor (same remedy as
        // resync, just for all channels at once)
        for (const ch of this.channels.values()) ch.lastEventId = null;
        return;
      case 'hello':
      case 'subscribed':
      case 'denied':
        return;
    }
  }

  private deliver(event: RealtimeEvent): void {
    // each delivery is already labeled with the one channel it matched (see to_message's
    // docstring server-side); a listener only ever hears about the channel it subscribed to,
    // so no cross-channel de-dup is needed here even when one change matches several channels
    const ch = this.channels.get(event.channel);
    if (!ch) return;
    ch.lastEventId = Math.max(ch.lastEventId ?? 0, event.id);
    for (const listener of ch.listeners) listener(event);
  }

  private send(msg: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private scheduleReconnect(): void {
    if (this.closed || this.reconnectTimer) return;
    const base = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)]!;
    const delay = base + Math.random() * Math.min(base, JITTER_CAP_MS);
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private setState(state: ConnectionState): void {
    if (this.state === state) return;
    this.state = state;
    for (const fn of this.stateListeners) fn(state);
  }
}

/** ws(s)://host/<basePath>/ws, matching the API's own origin-relative base path. */
export function realtimeUrl(basePath: string, origin = window.location.origin): string {
  const httpUrl = new URL(`${basePath || ''}/ws`, origin);
  httpUrl.protocol = httpUrl.protocol === 'https:' ? 'wss:' : 'ws:';
  return httpUrl.toString();
}
