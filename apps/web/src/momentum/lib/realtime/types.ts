/** Wire types for `GET /ws` (docs/architecture/realtime-jobs-events.md §3). Kept by hand:
 * this is a websocket protocol, not a REST schema, so it isn't in the generated OpenAPI types. */

export interface RealtimeEvent {
  type: 'event';
  id: number;
  event: string; // e.g. "task.updated" — matches Activity.verb / OutboxEvent.type
  entity_type: string;
  entity_id: string;
  /** Which of this connection's subscriptions this delivery is for — one underlying change
   * can match more than one subscribed channel (e.g. a task's own channel and its project's),
   * and then arrives once per match, each labeled. */
  channel: string;
  data: Record<string, unknown>;
  actor: { id: string | null; kind: string } | null;
  request_id: string | null;
  /** Present when the change was recorded (almost always). Lets the actor's own tab
   * recognize its own echo — see mine.ts. */
  activity_id: string | null;
}

export type ServerMessage =
  | { type: 'hello'; connection_id: string }
  | { type: 'subscribed'; channel: string }
  | { type: 'denied'; channel: string; reason: string }
  | { type: 'resync'; channel: string }
  | { type: 'overflow' }
  | { type: 'ping' }
  | RealtimeEvent;

export type ClientMessage =
  | { op: 'subscribe'; channel: string; since?: number }
  | { op: 'unsubscribe'; channel: string }
  | { op: 'pong' };

export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed';
