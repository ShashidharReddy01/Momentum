/** A tiny fake WebSocket for tests: no network, fully scripted by the test. Install with
 * `vi.stubGlobal('WebSocket', MockWebSocket)` before creating a RealtimeClient. */
export class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  sent: unknown[] = [];

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(code = 1000): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ code });
  }

  // test helpers, not part of the real WebSocket API
  open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  push(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  static latest(): MockWebSocket {
    const ws = MockWebSocket.instances.at(-1);
    if (!ws) throw new Error('no MockWebSocket was constructed');
    return ws;
  }

  static reset(): void {
    MockWebSocket.instances = [];
  }
}
