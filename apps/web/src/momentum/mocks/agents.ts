import { http, HttpResponse } from 'msw';
import type { Agent, AgentRun, AgentRunDetail } from '@/features/agents';
import type { components } from '@/lib/api/schema';

type AgentStats = components['schemas']['AgentStatsOut'];

/** Synthetic agent fixtures (S5.1.3). */
export function agentFixture(over: Partial<Agent> = {}): Agent {
  return {
    id: 'agent-1',
    user_id: 'agent-user-1',
    key: 'teammate',
    name: 'Teammate',
    avatar: 'teammate',
    description: 'A general-purpose teammate.',
    instructions: 'Do the work.',
    kind: 'llm',
    handler: null,
    triggers: [{ type: 'assigned' }],
    tools: ['get_task', 'add_comment'],
    scope: { projects: 'member_of' },
    autonomy: 'confirm',
    model_alias: 'default',
    budget_monthly_usd: '5.00',
    budget_monthly_tokens: 2000000,
    limits: {},
    enabled: true,
    source: 'starter',
    drifted: false,
    version: 1,
    created_at: '2026-09-28T10:00:00Z',
    updated_at: '2026-09-28T10:00:00Z',
    projects: [{ id: 'p-1', name: 'Website Revamp', role: 'editor' }],
    ...over,
  };
}

export function runFixture(over: Partial<AgentRunDetail> = {}): AgentRunDetail {
  return {
    id: 'run-1',
    agent: { id: 'agent-1', key: 'teammate', name: 'Teammate', avatar: 'teammate' },
    status: 'succeeded',
    trigger: 'assigned',
    task: { id: 't-1', key: 'T-12', title: 'Research competitor pricing' },
    project: null,
    requested_by: { id: 'u-1', name: 'Ravi Kumar' },
    created_at: '2026-09-28T10:00:00Z',
    started_at: '2026-09-28T10:00:05Z',
    finished_at: '2026-09-28T10:00:20Z',
    steps: 2,
    tokens_in: 1200,
    tokens_out: 300,
    cost_usd: '0.004000',
    error: null,
    proposals: 1,
    applied: 0,
    detail: 'full',
    trace: [
      { at: '2026-09-28T10:00:05Z', kind: 'trigger', summary: 'assigned trigger', name: null, ok: null },
      { at: '2026-09-28T10:00:09Z', kind: 'tool', summary: 'Found 3 tasks', name: 'search_tasks', ok: true },
      {
        at: '2026-09-28T10:00:15Z',
        kind: 'proposal',
        summary: 'Would set priority high',
        name: null,
        ok: null,
      },
      { at: '2026-09-28T10:00:20Z', kind: 'comment', summary: 'Research done', name: null, ok: null },
    ],
    answer: 'Research done: three competitors price per seat.',
    comment_id: 'c-1',
    actions: [],
    ...over,
  };
}

export function statsFixture(over: Partial<AgentStats> = {}): AgentStats {
  return {
    decided: 12,
    accepted: 11,
    acceptance_rate: 11 / 12,
    undos_14d: 0,
    auto_applied_7d: 0,
    auto_undone_7d: 0,
    eligible_for_auto: false,
    reasons: ['Needs 30 decided proposals to judge (has 12)'],
    month_usd: '1.250000',
    month_tokens: 120000,
    priced: true,
    ...over,
  };
}

export function agentHandlers(
  opts: { agent?: Agent; runs?: AgentRun[]; run?: AgentRunDetail; stats?: AgentStats } = {},
) {
  let agent = opts.agent ?? agentFixture();
  const patches: unknown[] = [];
  const run = opts.run ?? runFixture();
  const runs = opts.runs ?? [run];
  const queries: URLSearchParams[] = [];
  const handlers = [
    http.get('*/api/v1/agents/runs/:runId', () => HttpResponse.json(run)),
    http.get('*/api/v1/agents/:agentId/runs', ({ request }) => {
      const q = new URL(request.url).searchParams;
      queries.push(q);
      const data = runs.filter(
        (r) =>
          (!q.get('status') || r.status === q.get('status')) &&
          (!q.get('trigger') || r.trigger === q.get('trigger')),
      );
      return HttpResponse.json({ data, meta: { next_cursor: null } });
    }),
    http.get('*/api/v1/agents/:agentId/stats', () => HttpResponse.json(opts.stats ?? statsFixture())),
    http.get('*/api/v1/agents/:agentId', () => HttpResponse.json(agent)),
    http.patch('*/api/v1/agents/:agentId', async ({ request }) => {
      const body = (await request.json()) as Partial<Agent>;
      patches.push(body);
      agent = { ...agent, ...body, version: agent.version + 1 };
      return HttpResponse.json({
        data: agent,
        meta: { activity_id: 'act-9', batch_id: null, version: agent.version },
      });
    }),
  ];
  return { handlers, queries, patches };
}
