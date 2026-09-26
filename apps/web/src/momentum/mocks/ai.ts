import { http, HttpResponse } from 'msw';
import type { AiAction } from '@/features/ai';

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
