import { http, HttpResponse } from 'msw';
import { ravi } from './fixtures';

type Trigger = { type: string; [k: string]: unknown };
type Condition = { field: string; op: string; value?: unknown };
type Action = { type: string; [k: string]: unknown };
type R = {
  id: string;
  project_id: string | null;
  name: string;
  enabled: boolean;
  trigger: Trigger;
  conditions: Condition[];
  actions: Action[];
  created_from_prompt: string | null;
  version: number;
  created_by: string;
  created_at: string;
  updated_at: string;
};
type Run = {
  id: string;
  rule_id: string;
  outbox_event_id: number;
  status: string;
  depth: number;
  actions_run: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  activity_batch_id: string | null;
};

/** In-memory S4.1.1-S4.1.4 rules API: CRUD, run history, a canned "test run" (every action comes
 * back `ok: true` — the backend's own conditions/action logic is covered in test_rules.py; this
 * mock only needs to exercise the builder UI) and a canned NL compile. */
export function ruleHandlers(base = '', seedRuns: Record<string, Run[]> = {}) {
  const rules: R[] = [];
  const runs: Record<string, Run[]> = { ...seedRuns };
  let n = 0;
  const now = '2026-09-27T00:00:00Z';

  return [
    http.get(`*${base}/api/v1/rules`, ({ request }) => {
      const url = new URL(request.url);
      const projectId = url.searchParams.get('project_id');
      return HttpResponse.json({
        data: rules.filter((r) => r.project_id === projectId),
        meta: { next_cursor: null },
      });
    }),
    http.post(`*${base}/api/v1/rules`, async ({ request }) => {
      const b = (await request.json()) as Omit<
        R,
        'id' | 'version' | 'created_by' | 'created_at' | 'updated_at'
      >;
      const r: R = {
        ...b,
        id: `rule-${++n}`,
        version: 1,
        created_by: 'user-1',
        created_at: now,
        updated_at: now,
      };
      rules.push(r);
      return HttpResponse.json(
        { data: r, meta: { activity_id: null, batch_id: null, version: 1 } },
        { status: 201 },
      );
    }),
    http.get(`*${base}/api/v1/rules/:id`, ({ params }) => {
      const r = rules.find((x) => x.id === params.id);
      if (!r) return HttpResponse.json({ detail: 'not found' }, { status: 404 });
      return HttpResponse.json(r);
    }),
    http.patch(`*${base}/api/v1/rules/:id`, async ({ params, request }) => {
      const r = rules.find((x) => x.id === params.id)!;
      const b = (await request.json()) as Partial<R>;
      Object.assign(r, b);
      r.version += 1;
      return HttpResponse.json({ data: r, meta: { activity_id: null, batch_id: null, version: r.version } });
    }),
    http.delete(`*${base}/api/v1/rules/:id`, ({ params }) => {
      const i = rules.findIndex((r) => r.id === params.id);
      if (i >= 0) rules.splice(i, 1);
      return HttpResponse.json({ ok: true });
    }),
    http.get(`*${base}/api/v1/rules/:id/runs`, ({ params }) =>
      HttpResponse.json({ data: runs[String(params.id)] ?? [], meta: { next_cursor: null } }),
    ),
    // S4.1.4: a sentence naming a section and a person compiles; anything else asks back.
    http.post(`*${base}/api/v1/ai/rules/compile`, async ({ request }) => {
      const b = (await request.json()) as { project_id: string; text: string };
      if (!/review/i.test(b.text))
        return HttpResponse.json({
          rule: null,
          sentence: null,
          question: "I can't do that yet. Which section should the task move into?",
        });
      return HttpResponse.json({
        rule: {
          name: 'Review goes to Ravi',
          enabled: true,
          trigger: { type: 'task.moved', to_section: 'sec-1' },
          conditions: [],
          actions: [{ type: 'assign', user_id: ravi.id }],
          created_from_prompt: b.text,
        },
        sentence: 'When a task moves to Review, then assign to Ravi Kumar.',
        question: null,
      });
    }),
    http.post(`*${base}/api/v1/rules/:id/test-run`, ({ params }) => {
      const r = rules.find((x) => x.id === params.id);
      return HttpResponse.json({
        conditions_passed: true,
        actions: (r?.actions ?? []).map((a) => ({ type: a.type, ok: true, error: null })),
      });
    }),
  ];
}
