import { http, HttpResponse } from 'msw';
import type { Agent, AgentRun, AgentRunDetail } from '@/features/agents';
import type { components } from '@/lib/api/schema';

type AgentStats = components['schemas']['AgentStatsOut'];
type DirectoryCard = components['schemas']['DirectoryCardOut'];
type AgentProfile = components['schemas']['ProfileOut'];
type AgentHealth = components['schemas']['HealthOut'];
type PackSettings = components['schemas']['PackSettingsOut'];

/** Phase 7.6 S76-07: a directory card built from an agent (synthetic). */
export function cardFixture(agent: Agent, over: Partial<DirectoryCard> = {}): DirectoryCard {
  return {
    id: agent.id,
    user_id: agent.user_id,
    key: agent.key,
    name: agent.name,
    avatar: agent.avatar,
    description: agent.description,
    enabled: agent.enabled,
    source: agent.source,
    title: null,
    capabilities: [],
    data_class: null,
    health: null,
    ...over,
  };
}

export function profileFixture(over: Partial<AgentProfile> = {}): AgentProfile {
  return {
    agent_id: 'agent-1',
    is_pack: false,
    title: null,
    charter: 'A general-purpose teammate.',
    capabilities: [],
    effects: [],
    triggers: ['When a task is assigned to it'],
    data_class: null,
    personal_data: null,
    reads_external_content: false,
    has_settings: false,
    can_assign: true,
    can_mention: false,
    can_run: false,
    ...over,
  };
}

export function healthFixture(over: Partial<AgentHealth> = {}): AgentHealth {
  return {
    agent_id: 'agent-1',
    days: 30,
    detail: false,
    jobs: 0,
    items: 0,
    success_rate: null,
    median_active_seconds: null,
    median_waiting_seconds: null,
    asks_per_item: null,
    median_answer_seconds: null,
    human_touch_rate: null,
    auto_approved_rate: null,
    cost_per_item_usd: null,
    skills: null,
    time_saved_minutes: null,
    time_saved_is_estimate: true,
    top_corrected_fields: null,
    calibration: null,
    top_failure_reasons: null,
    ...over,
  };
}

/** A pack's settings as the server returns them (echo-like: every widget kind). */
export function packSettingsFixture(over: Partial<PackSettings> = {}): PackSettings {
  return {
    agent_id: 'agent-1',
    pack_key: 'echo',
    project_id: null,
    form: {
      title: 'EchoSettings',
      type: 'object',
      properties: {
        stewards: {
          title: 'Stewards',
          description: 'People who look after Echo',
          type: 'array',
          ui: 'people',
        },
        threshold: { title: 'Threshold', description: 'A number', type: 'integer', ui: 'int', default: 100 },
        watch_uploads: {
          title: 'Watch uploads',
          description: 'Run on every upload',
          type: 'boolean',
          ui: 'bool',
        },
        tone: {
          title: 'Tone',
          description: 'How Echo writes',
          type: 'string',
          ui: 'enum',
          options: ['plain', 'friendly'],
        },
        confidence_floor: { title: 'Confidence floor', type: 'number', ui: 'percent', default: 0.85 },
        materiality: { title: 'Materiality', type: 'object', ui: 'money_by_currency' },
        sections: { title: 'Watched sections', type: 'array', ui: 'text_list' },
      },
    },
    workspace: {},
    project: null,
    effective: {
      stewards: [],
      threshold: 100,
      watch_uploads: false,
      tone: 'plain',
      confidence_floor: 0.85,
      materiality: { USD: '5000' },
      sections: [],
    },
    can_edit: true,
    activity_id: null,
    ...over,
  };
}

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
    mode: 'oneshot',
    capability: null,
    parent_run_id: null,
    waiting_on: null,
    progress: null,
    attempt: 0,
    active_seconds: 0,
    job_steps: [],
    children: [],
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
  opts: {
    agent?: Agent;
    runs?: AgentRun[];
    run?: AgentRunDetail;
    stats?: AgentStats;
    list?: Agent[];
    cards?: DirectoryCard[];
    profile?: AgentProfile;
    health?: AgentHealth;
    settings?: PackSettings;
  } = {},
) {
  let agent = opts.agent ?? agentFixture();
  const patches: unknown[] = [];
  const run = opts.run ?? runFixture();
  const runs = opts.runs ?? [run];
  const queries: URLSearchParams[] = [];
  const creates: unknown[] = [];
  const testRuns: unknown[] = [];
  const runsNow: unknown[] = [];
  const added: unknown[] = [];
  const list = opts.list ?? [agent];
  const cards = opts.cards ?? list.map((a) => cardFixture(a));
  const directoryQueries: URLSearchParams[] = [];
  const settingsPuts: { projectId: string | null; values: unknown }[] = [];
  let settings = opts.settings ?? packSettingsFixture();
  const handlers = [
    // Phase 7.6 S76-07: directory, profile, health, pack settings
    http.get('*/api/v1/agents/directory', ({ request }) => {
      const q = new URL(request.url).searchParams;
      directoryQueries.push(q);
      const words = (q.get('q') ?? '')
        .toLowerCase()
        .split(/\W+/)
        .filter((w) => w.length > 3);
      const data = cards.filter(
        (c) =>
          (!q.get('enabled') || String(c.enabled) === q.get('enabled')) &&
          (!q.get('data_class') || c.data_class === q.get('data_class')) &&
          (!q.get('capability') || c.capabilities.some((x) => x.key === q.get('capability'))) &&
          words.every((w) =>
            `${c.name} ${c.title ?? ''} ${c.description} ${c.capabilities.map((x) => `${x.title} ${x.description}`).join(' ')}`
              .toLowerCase()
              .includes(w.replace(/s$/, '')),
          ),
      );
      return HttpResponse.json({ data, meta: { next_cursor: null } });
    }),
    http.get('*/api/v1/agents/:agentId/profile', () => HttpResponse.json(opts.profile ?? profileFixture())),
    http.get('*/api/v1/agents/:agentId/health', ({ request }) => {
      const days = Number(new URL(request.url).searchParams.get('days') ?? 30);
      return HttpResponse.json({ ...(opts.health ?? healthFixture()), days });
    }),
    http.get('*/api/v1/agents/:agentId/settings', ({ request }) => {
      const projectId = new URL(request.url).searchParams.get('project_id');
      return HttpResponse.json({ ...settings, project_id: projectId, project: projectId ? {} : null });
    }),
    http.put('*/api/v1/agents/:agentId/settings', async ({ request }) => {
      const projectId = new URL(request.url).searchParams.get('project_id');
      const { values } = (await request.json()) as { values: Record<string, unknown> };
      settingsPuts.push({ projectId, values });
      settings = {
        ...settings,
        workspace: projectId ? settings.workspace : values,
        effective: { ...settings.effective, ...values },
        activity_id: 'act-settings',
      };
      return HttpResponse.json(settings);
    }),
    // S5.2.3: gallery, tools, draft, create, test run
    http.get('*/api/v1/agents', () => HttpResponse.json({ data: list, meta: { next_cursor: null } })),
    http.get('*/api/v1/agents/tools', () =>
      HttpResponse.json({
        data: [
          { name: 'get_task', description: 'Read a task', risk: 'read' },
          { name: 'search_tasks', description: 'Find tasks', risk: 'read' },
          { name: 'add_comment', description: 'Comment on a task', risk: 'low' },
        ],
        meta: { next_cursor: null },
      }),
    ),
    http.post('*/api/v1/agents/draft', () =>
      HttpResponse.json({
        agent: {
          name: '(mock) Bug Sweeper',
          description: '(mock) Flags stale bugs every Monday.',
          instructions: '(mock) You review open bugs each Monday.',
          triggers: [{ type: 'schedule', cron: '0 9 * * MON', timezone: 'workspace' }, { type: 'mentioned' }],
          tools: ['search_tasks', 'add_comment'],
          autonomy: 'confirm',
          model_alias: 'fast',
          avatar: 'teammate',
          kind: 'llm',
          budget_monthly_usd: '5',
          budget_monthly_tokens: 2000000,
        },
        notes: ['Left out delete_task: agents never delete or decide approvals.'],
      }),
    ),
    http.post('*/api/v1/agents', async ({ request }) => {
      const body = (await request.json()) as Partial<Agent>;
      creates.push(body);
      const created = agentFixture({ ...body, id: 'agent-new', enabled: false, source: 'custom' });
      return HttpResponse.json(
        { data: created, meta: { activity_id: 'act-1', batch_id: null, version: 1 } },
        { status: 201 },
      );
    }),
    http.post('*/api/v1/agents/:agentId/projects', async ({ request }) => {
      const body = (await request.json()) as { project_id: string; role: string };
      added.push(body);
      agent = {
        ...agent,
        projects: [
          ...(agent.projects ?? []),
          { id: body.project_id, name: 'Added project', role: body.role },
        ],
      };
      return HttpResponse.json(
        { data: { ok: true }, meta: { activity_id: 'act-5', batch_id: null, version: null } },
        { status: 201 },
      );
    }),
    http.post('*/api/v1/agents/:agentId/run', async ({ request }) => {
      runsNow.push(await request.json());
      return HttpResponse.json({ run_id: 'run-1', status: 'queued' }, { status: 202 });
    }),
    http.post('*/api/v1/agents/:agentId/test-run', async ({ request }) => {
      testRuns.push(await request.json());
      return HttpResponse.json({
        text: '(mock) I would raise the priority.',
        steps: 2,
        trace: [{ kind: 'tool', summary: 'Previewed a change', name: 'update_task', ok: true }],
        changes: [
          {
            tool: 'update_task',
            summary: 'Set priority to high on T-12',
            risk: 'low',
            decision: 'would propose to the person who asked',
          },
        ],
        tokens_in: 900,
        tokens_out: 60,
      });
    }),
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
  return { handlers, queries, patches, creates, testRuns, runsNow, added, directoryQueries, settingsPuts };
}
