import { http, HttpResponse } from 'msw';
import type { components } from '@/lib/api/schema';

type Ask = components['schemas']['AskOut'];
type TaskJob = components['schemas']['TaskJobOut'];

/** Phase 7.6 S76-07: synthetic agent questions and jobs. */
export function askFixture(over: Partial<Ask> = {}): Ask {
  return {
    id: 'ask-1',
    run_id: 'run-9',
    task_id: 't-1',
    comment_id: 'c-ask',
    agent: { id: 'agent-1', name: 'Echo', avatar: 'teammate' },
    kind: 'choice',
    title: 'Which vendor is this?',
    body: 'Two vendors look alike.',
    evidence: [{ page: 1, excerpt: 'Globex Ltd' }],
    options: [
      { value: 'globex', label: 'Globex' },
      { value: 'initech', label: 'Initech' },
    ],
    form: null,
    route: 'requester',
    route_fallback: null,
    status: 'open',
    answer: null,
    answered_by: null,
    answered_via: null,
    to: [{ id: 'u-1', name: 'Ravi Kumar' }],
    can_answer: true,
    default_on_expiry: { action: 'fail' },
    created_at: '2026-10-08T10:00:00Z',
    answered_at: null,
    expires_at: '2026-10-15T10:00:00Z',
    change_activity_id: null,
    ...over,
  };
}

export function taskJobFixture(over: Partial<TaskJob> = {}): TaskJob {
  return {
    id: 'run-9',
    agent: { id: 'agent-1', key: 'echo', name: 'Echo', avatar: 'teammate' },
    status: 'waiting',
    mode: 'job',
    capability: 'echo',
    parent_run_id: null,
    waiting_on: 'ask',
    progress: { done: 2, total: 5, label: 'invoices' },
    attempt: 0,
    active_seconds: 12,
    trigger: 'assigned',
    task: { id: 't-1', key: 'T-12', title: 'Research competitor pricing' },
    project: null,
    requested_by: { id: 'u-1', name: 'Ravi Kumar' },
    created_at: '2026-10-08T10:00:00Z',
    started_at: '2026-10-08T10:00:01Z',
    finished_at: null,
    steps: 0,
    tokens_in: 0,
    tokens_out: 0,
    cost_usd: '0',
    error: null,
    proposals: 0,
    applied: 0,
    current_step: 'vendor',
    waiting_reason: 'Waiting for an answer: “Which vendor is this?”',
    asks_for_me: 1,
    ...over,
  };
}

/** Asks and jobs with answers recorded; answering closes the question (as the server does). */
export function askHandlers(opts: { asks?: Ask[]; jobs?: TaskJob[]; interpret?: 'certain' | 'unsure' } = {}) {
  const asks = new Map((opts.asks ?? [askFixture()]).map((a) => [a.id, a]));
  let jobs = opts.jobs ?? [];
  const answers: { id: string; value: unknown; via: string }[] = [];
  const interpreted: { id: string; text: string }[] = [];
  const controls: string[] = [];
  const label = (a: Ask, v: unknown) =>
    (a.options ?? []).find((o) => (o as { value: string }).value === v)?.label ?? String(v);
  const answer = (a: Ask, value: unknown, via: string): Ask => {
    const done: Ask = {
      ...a,
      status: 'answered',
      answer: value,
      answered_via: via,
      answered_by: { id: 'u-1', name: 'Ravi Kumar' },
      answered_at: '2026-10-08T10:05:00Z',
      can_answer: false,
      change_activity_id: 'act-answer',
    };
    asks.set(a.id, done);
    jobs = jobs.map((j) =>
      j.id === a.run_id
        ? { ...j, status: 'running', waiting_on: null, waiting_reason: null, asks_for_me: 0 }
        : j,
    );
    return done;
  };
  const handlers = [
    http.get('*/api/v1/asks', () =>
      HttpResponse.json({
        data: [...asks.values()].filter((a) => a.status === 'open'),
        meta: { next_cursor: null },
      }),
    ),
    http.get('*/api/v1/asks/:id', ({ params }) => {
      const a = asks.get(String(params.id));
      return a
        ? HttpResponse.json(a)
        : HttpResponse.json({ error: { code: 'not_found', message: 'Not found' } }, { status: 404 });
    }),
    http.post('*/api/v1/asks/:id/answer', async ({ params, request }) => {
      const body = (await request.json()) as { value: unknown; via: string };
      answers.push({ id: String(params.id), ...body });
      return HttpResponse.json(answer(asks.get(String(params.id))!, body.value, body.via));
    }),
    http.post('*/api/v1/asks/:id/interpret', async ({ params, request }) => {
      const { text } = (await request.json()) as { text: string };
      interpreted.push({ id: String(params.id), text });
      const a = asks.get(String(params.id))!;
      if (opts.interpret === 'unsure')
        return HttpResponse.json({
          applied: false,
          certain: false,
          value: 'globex',
          understood: 'Globex',
          ask: a,
        });
      const done = answer(a, 'globex', 'thread');
      return HttpResponse.json({
        applied: true,
        certain: true,
        value: 'globex',
        understood: label(a, 'globex'),
        ask: done,
      });
    }),
    http.get('*/api/v1/tasks/:id/jobs', () => HttpResponse.json({ data: jobs, meta: { next_cursor: null } })),
    http.post('*/api/v1/agents/runs/:runId/:action', ({ params }) => {
      controls.push(String(params.action));
      if (params.action === 'undo')
        return HttpResponse.json({
          undone: 3,
          skipped: [{ entity_type: 'task', entity_id: 't-1', verb: 'task.updated', reason: 'edited since' }],
        });
      const status =
        params.action === 'pause' ? 'paused' : params.action === 'cancel' ? 'cancelled' : 'queued';
      jobs = jobs.map((j) => (j.id === params.runId ? { ...j, status } : j));
      return HttpResponse.json({ run_id: params.runId, status });
    }),
  ];
  return { handlers, answers, interpreted, controls };
}
