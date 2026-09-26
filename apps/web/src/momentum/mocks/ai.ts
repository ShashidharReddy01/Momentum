import { http, HttpResponse } from 'msw';
import type { AiAction } from '@/features/ai';
import type { components } from '@/lib/api/schema';

const problem = (status: number, code: string, detail: string) =>
  HttpResponse.json(
    { code, title: 'Conflict', status, detail },
    { status, headers: { 'content-type': 'application/problem+json' } },
  );

/** A proposed action fixture (S3.1.3). Mock data: tests and dev only. */
export function aiActionFixture(over: Partial<AiAction> = {}): AiAction {
  return {
    id: 'act-1',
    source: 'command',
    summary: 'Would update T-12 Draft pricing copy',
    risk: 'low',
    state: 'proposed',
    operations: [
      {
        tool: 'update_task',
        args: { task: 'T-12', due_on: '2026-10-09' },
        summary: 'Would update T-12 Draft pricing copy',
        risk: 'low',
        diff: [
          {
            entity_type: 'task',
            entity_id: 'task-12',
            label: 'T-12 Draft pricing copy',
            verb: 'task.updated',
            changes: { due_on: [null, '2026-10-09'], assignee_id: [null, 'u-ana'] },
            display: { due_on: [null, '2026-10-09'], assignee_id: [null, 'Ana Souza'] },
          },
        ],
      },
    ],
    applied_batch_id: null,
    error: null,
    created_at: '2026-09-26T10:00:00Z',
    expires_at: '2026-09-27T10:00:00Z',
    decided_at: null,
    ...over,
  };
}

/** In-memory AI actions API. `staleOnce` makes the first apply come back re-previewed, the way
 * the server answers when a target changed after the preview. */
export function aiHandlers(initial: AiAction[], opts: { staleOnce?: boolean } = {}) {
  const actions = new Map(initial.map((a) => [a.id, structuredClone(a)]));
  const calls: { path: string; body: unknown }[] = [];
  let stale = opts.staleOnce ?? false;
  const get = (id: string) => actions.get(id)!;
  const handlers = [
    http.get('*/api/v1/ai/actions/:id', ({ params }) => {
      const a = actions.get(String(params.id));
      return a ? HttpResponse.json({ data: a }) : problem(404, 'not_found', 'Action not found');
    }),
    http.post('*/api/v1/ai/actions/:id/apply', async ({ params, request }) => {
      const body = (await request.json()) as { confirm_high_risk?: boolean };
      calls.push({ path: 'apply', body });
      const a = get(String(params.id));
      if (a.state !== 'proposed') return problem(409, 'action_not_pending', 'Already decided');
      if (a.risk === 'high' && !body.confirm_high_risk)
        return problem(409, 'confirmation_required', 'Needs confirmation');
      if (stale) {
        stale = false;
        a.operations[0]!.diff[0]!.label = 'T-12 Pricing copy (final)';
        return HttpResponse.json({ data: a, outcome: 'repreviewed' });
      }
      a.state = 'applied';
      a.applied_batch_id = 'batch-1';
      return HttpResponse.json({ data: a, outcome: 'applied' });
    }),
    http.post('*/api/v1/ai/actions/:id/reject', ({ params }) => {
      calls.push({ path: 'reject', body: null });
      const a = get(String(params.id));
      a.state = 'rejected';
      return HttpResponse.json({ data: a });
    }),
    http.post('*/api/v1/ai/actions/:id/undo', ({ params }) => {
      calls.push({ path: 'undo', body: null });
      const a = get(String(params.id));
      a.state = 'undone';
      return HttpResponse.json({ data: a });
    }),
  ];
  return { handlers, calls };
}

type Bullet = {
  id: string;
  scope: 'workspace';
  scope_id: null;
  text: string;
  created_at: string;
  updated_at: string;
};

/** In-memory workspace memory API (S3.1.5). `canEdit: false` answers writes with 403, as the
 * server does for non-admins. */
export function aiMemoryHandlers(initial: string[] = [], opts: { canEdit?: boolean } = {}) {
  let n = 0;
  const at = '2026-09-26T10:00:00Z';
  const mk = (text: string): Bullet => ({
    id: `mem-${++n}`,
    scope: 'workspace',
    scope_id: null,
    text,
    created_at: at,
    updated_at: at,
  });
  const bullets = initial.map(mk);
  const meta = () => ({
    activity_id: `01a0ccaf-0000-7000-8000-0000000${String(900 + n)}`,
    batch_id: null,
    version: null,
  });
  const forbidden = () =>
    HttpResponse.json(
      { code: 'forbidden', title: 'Forbidden', status: 403, detail: 'Admins only' },
      { status: 403, headers: { 'content-type': 'application/problem+json' } },
    );
  const canEdit = opts.canEdit ?? true;
  const handlers = [
    http.get('*/api/v1/ai/memory', () => HttpResponse.json({ data: bullets, meta: { next_cursor: null } })),
    http.post('*/api/v1/ai/memory', async ({ request }) => {
      if (!canEdit) return forbidden();
      const b = (await request.json()) as { text: string };
      const x = mk(b.text);
      bullets.push(x);
      return HttpResponse.json({ data: x, meta: meta() }, { status: 201 });
    }),
    http.patch('*/api/v1/ai/memory/:id', async ({ params, request }) => {
      if (!canEdit) return forbidden();
      const x = bullets.find((b) => b.id === params.id)!;
      x.text = ((await request.json()) as { text: string }).text;
      return HttpResponse.json({ data: x, meta: meta() });
    }),
    http.delete('*/api/v1/ai/memory/:id', ({ params }) => {
      if (!canEdit) return forbidden();
      const i = bullets.findIndex((b) => b.id === params.id);
      const [x] = bullets.splice(i, 1);
      return HttpResponse.json({ data: x, meta: meta() });
    }),
  ];
  return { handlers, bullets };
}

type AiConfig = components['schemas']['AiConfig'];
type EffectiveAi = components['schemas']['EffectiveAi'];
type UsageReport = components['schemas']['UsageReport'];

function effectiveOf(c: AiConfig): EffectiveAi {
  return {
    enabled: c.enabled !== false,
    monthly_budget_usd: c.monthly_budget_usd ?? 0,
    allow_auto_apply: c.allow_auto_apply !== false,
  };
}

/** Admin AI settings + usage (S3.5.2). `canEdit: false` answers with 403, as the server does for
 * non-admins. `usage` defaults to an empty report. */
export function aiAdminHandlers(
  initialConfig: AiConfig = {},
  usage: Partial<UsageReport> = {},
  opts: { canEdit?: boolean } = {},
) {
  let config: AiConfig = { ...initialConfig };
  const canEdit = opts.canEdit ?? true;
  const models = {
    fast: 'provider/chat-fast',
    default: 'provider/chat-default',
    smart: 'provider/chat-smart',
    embed: 'provider/embed',
  };
  const report: UsageReport = {
    since: '2026-08-27T00:00:00Z',
    month_spend_usd: '0.00',
    monthly_budget_usd: 0,
    by_feature: [],
    by_user: [],
    by_day: [],
    ...usage,
  };
  const forbidden = () =>
    HttpResponse.json(
      { code: 'forbidden', title: 'Forbidden', status: 403, detail: 'Admins only' },
      { status: 403, headers: { 'content-type': 'application/problem+json' } },
    );
  const handlers = [
    http.get('*/api/v1/ai/admin/settings', () =>
      canEdit ? HttpResponse.json({ config, effective: effectiveOf(config), models }) : forbidden(),
    ),
    http.put('*/api/v1/ai/admin/settings', async ({ request }) => {
      if (!canEdit) return forbidden();
      config = (await request.json()) as AiConfig;
      return HttpResponse.json({
        data: effectiveOf(config),
        meta: { activity_id: '01a0ccaf-0000-7000-8000-000000000901', batch_id: null, version: null },
      });
    }),
    http.get('*/api/v1/ai/admin/usage', () => (canEdit ? HttpResponse.json(report) : forbidden())),
  ];
  return { handlers, config: () => config };
}

export type ScriptedEvent = [string, Record<string, unknown>];

/** `POST /ai/command` as an SSE stream of scripted events (S3.2.2); one script per request, in
 * order. Records each request body. */
export function aiCommandHandlers(scripts: ScriptedEvent[][], prefs = { auto_apply_low_risk: false }) {
  const requests: { text: string; screen?: unknown }[] = [];
  const saved: unknown[] = [];
  const handlers = [
    http.post('*/api/v1/ai/command', async ({ request }) => {
      requests.push((await request.json()) as { text: string });
      const script = scripts.shift() ?? [['done', { steps: 0 }]];
      const body = script
        .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
        .join('');
      return new HttpResponse(body, { headers: { 'content-type': 'text/event-stream' } });
    }),
    http.get('*/api/v1/ai/prefs', () => HttpResponse.json(prefs)),
    http.put('*/api/v1/ai/prefs', async ({ request }) => {
      const b = (await request.json()) as typeof prefs;
      saved.push(b);
      Object.assign(prefs, b);
      return HttpResponse.json(prefs);
    }),
  ];
  return { handlers, requests, saved };
}

type ChatMessage = components['schemas']['ChatMessageOut'];
type Conversation = components['schemas']['ConversationOut'];

/** Ask Mo chat (S3.3.1): `POST /ai/chat` streams one scripted event list per request, in order;
 * conversations and their messages are served from `stored`; feedback is recorded. */
export function aiChatHandlers(
  scripts: ScriptedEvent[][],
  stored: { conversation: Conversation; messages: ChatMessage[] }[] = [],
) {
  const requests: { text: string; conversation_id?: string | null; screen?: unknown }[] = [];
  const feedback: unknown[] = [];
  const handlers = [
    http.post('*/api/v1/ai/chat', async ({ request }) => {
      requests.push((await request.json()) as { text: string });
      const script = scripts.shift() ?? [['done', { steps: 0 }]];
      const body = script
        .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
        .join('');
      return new HttpResponse(body, { headers: { 'content-type': 'text/event-stream' } });
    }),
    http.get('*/api/v1/ai/conversations', () =>
      HttpResponse.json({ data: stored.map((s) => s.conversation), meta: { next_cursor: null } }),
    ),
    http.get('*/api/v1/ai/conversations/:id', ({ params }) => {
      const s = stored.find((x) => x.conversation.id === params.id);
      return s
        ? HttpResponse.json({ data: s.conversation, messages: s.messages })
        : problem(404, 'not_found', 'Conversation not found');
    }),
    http.put('*/api/v1/ai/feedback', async ({ request }) => {
      const b = (await request.json()) as Record<string, unknown>;
      feedback.push(b);
      return HttpResponse.json({ comment: null, ...b });
    }),
  ];
  return { handlers, requests, feedback };
}
