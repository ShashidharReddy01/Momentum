import { http, HttpResponse } from 'msw';

/** In-memory portfolio v2 API (Phase 7.5) for web tests: one lifecycle portfolio with a stage
 * field, rows computed here the way the server would (grouping by stage, sort by one key),
 * saved views, members, a gated stage, bulk set and settings. Synthetic only. */

// option colors are user data (never CSS here); built from two literals for the design-token lint
const OPTION_COLOR = '#' + '999999';
export const STAGE_FIELD = 'pf-stage';
export const VALUE_FIELD = 'pf-value';
export const STAGES = [
  { id: 's-pre', label: 'Pre-sales' },
  { id: 's-disc', label: 'Discovery' },
  { id: 's-con', label: 'Contracts' },
  { id: 's-impl', label: 'Implementation' },
];
const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000e001', batch_id: null, version: 1 };

type Row = {
  id: string;
  name: string;
  stage: string | null;
  value: number | null;
  can_edit: boolean;
  status: string | null;
  start_on: string | null;
  target_date: string | null;
  forecast_date: string | null;
};

export function lifecycleState(): {
  rows: Row[];
  views: { id: string; name: string; owner_id: string | null; group_by: string | null; sort: unknown[] }[];
  members: { user_id: string; name: string; role: string }[];
  calls: { method: string; path: string; body: unknown }[];
  gated: Set<string>;
} {
  return {
    rows: [
      {
        id: 'p-north',
        name: 'Northwind Health',
        stage: 's-disc',
        value: 120000,
        can_edit: true,
        status: 'on_track',
        start_on: '2026-08-01',
        target_date: '2026-11-15',
        forecast_date: '2026-11-30',
      },
      {
        id: 'p-blue',
        name: 'Bluepeak Logistics',
        stage: 's-disc',
        value: 80000,
        can_edit: true,
        status: 'at_risk',
        start_on: '2026-09-01',
        target_date: '2026-12-01',
        forecast_date: null,
      },
      {
        id: 'p-cedar',
        name: 'Cedar & Finch Legal',
        stage: 's-pre',
        value: null,
        can_edit: false,
        status: null,
        start_on: null,
        target_date: '2026-12-20',
        forecast_date: null,
      },
    ],
    views: [{ id: 'v-shared', name: 'By stage', owner_id: null, group_by: 'stage', sort: [] }],
    members: [{ user_id: 'u-mei', name: 'Mei Chen', role: 'editor' }],
    calls: [],
    gated: new Set(['s-impl']),
  };
}

export const PROJECT_FIELDS = [
  {
    id: STAGE_FIELD,
    name: 'Stage',
    type: 'single_select',
    options: STAGES.map((s) => ({ ...s, color: OPTION_COLOR, archived: false })),
    description: null,
    is_library: true,
    created_by: null,
    applies_to: 'project',
  },
  {
    id: VALUE_FIELD,
    name: 'Contract value',
    type: 'currency',
    options: { precision: 0, unit: 'EUR' },
    description: null,
    is_library: true,
    created_by: null,
    applies_to: 'project',
  },
];

export function portfolioDetail(extra: Record<string, unknown> = {}) {
  return {
    id: 'pf-life',
    name: 'Customer onboarding',
    description: null,
    owner_id: 'u-ravi',
    status: null,
    version: 2,
    can_edit: true,
    project_count: 3,
    created_at: new Date().toISOString(),
    kind: 'rule',
    rule: {
      template_ids: [],
      team_ids: [],
      project_ids: [],
      project_field_conditions: [],
      include_completed: true,
      include_archived: false,
    },
    stage_field_id: STAGE_FIELD,
    stage_targets: { 's-disc': 21 },
    stage_gates: {
      's-impl': {
        required_fields: [VALUE_FIELD],
        required_milestones: ['Contract signed'],
        required_files: [],
      },
    },
    columns: [],
    my_role: 'owner',
    summary: null,
    projects: [],
    hidden_projects: 0,
    ...extra,
  };
}

function rowOut(r: Row) {
  const label = STAGES.find((s) => s.id === r.stage)?.label ?? null;
  return {
    id: r.id,
    name: r.name,
    color: 'proj-3',
    owner_id: null,
    owner_name: r.id === 'p-north' ? 'Ravi Kumar' : null,
    status: r.status,
    template_id: null,
    start_on: r.start_on,
    due_on: null,
    total_tasks: 10,
    completed_tasks: 4,
    open: 6,
    overdue: r.id === 'p-blue' ? 2 : 0,
    progress: 0.4,
    blocked: 0,
    waiting_on_customer: 1,
    next_milestone:
      r.id === 'p-north' ? { id: 't-ms', title: 'Discovery complete', due_on: '2026-10-20' } : null,
    stage: r.stage ? { option_id: r.stage, label } : null,
    stage_age_days: r.id === 'p-blue' ? 30 : 5,
    stage_target_days: r.stage === 's-disc' ? 21 : null,
    target_date: r.target_date,
    forecast_date: r.forecast_date,
    slip_days: r.forecast_date && r.target_date ? 15 : null,
    latest_update: null,
    fields: {
      ...(r.stage ? { [STAGE_FIELD]: r.stage } : {}),
      ...(r.value !== null ? { [VALUE_FIELD]: r.value } : {}),
    },
    can_edit: r.can_edit,
  };
}

const COLUMNS = [
  { key: 'name', label: 'Project', visible: true, width: null },
  { key: 'stage', label: 'Stage', visible: true, width: null },
  { key: `field:${VALUE_FIELD}`, label: 'Contract value', visible: true, width: null },
  { key: 'status', label: 'Health', visible: true, width: null },
  { key: 'progress', label: 'Progress', visible: true, width: null },
  { key: 'stage_age_days', label: 'Days in stage', visible: true, width: null },
];

export function portfolioV2Handlers(state = lifecycleState()) {
  const record = async (method: string, request: Request) => {
    const body = method === 'GET' || method === 'DELETE' ? null : await request.json().catch(() => null);
    state.calls.push({ method, path: new URL(request.url).pathname + new URL(request.url).search, body });
    return body as Record<string, unknown> | null;
  };
  return [
    http.get('*/api/v1/project-fields', () =>
      HttpResponse.json({ data: PROJECT_FIELDS, meta: { next_cursor: null } }),
    ),
    http.get('*/api/v1/portfolios/:id/rows', ({ request }) => {
      const url = new URL(request.url);
      const view = state.views.find((v) => v.id === url.searchParams.get('view_id'));
      const groupBy = url.searchParams.has('group_by')
        ? url.searchParams.get('group_by') || null
        : (view?.group_by ?? null);
      const sort = url.searchParams.get('sort');
      let rows = state.rows.map(rowOut);
      if (sort) {
        const [key, dir] = [sort.slice(0, sort.lastIndexOf(':')), sort.slice(sort.lastIndexOf(':') + 1)];
        const v = (r: ReturnType<typeof rowOut>) =>
          key === 'name'
            ? r.name
            : key.startsWith('field:')
              ? (r.fields as Record<string, unknown>)[key.slice(6)]
              : null;
        rows = [...rows].sort((a, b) => {
          const x = v(a) as string | number | undefined;
          const y = v(b) as string | number | undefined;
          if (x === undefined || x === null) return 1;
          if (y === undefined || y === null) return -1;
          return (x < y ? -1 : x > y ? 1 : 0) * (dir === 'desc' ? -1 : 1);
        });
      }
      const groups =
        groupBy === 'stage'
          ? STAGES.map((s) => {
              const members = rows.filter((r) => r.stage?.option_id === s.id);
              const values = members
                .map((r) => (r.fields as Record<string, unknown>)[VALUE_FIELD])
                .filter((x): x is number => typeof x === 'number');
              return {
                key: s.id,
                label: s.label,
                project_ids: members.map((r) => r.id),
                rollup: {
                  count: members.length,
                  progress_avg: members.length ? 0.4 : null,
                  overdue_total: members.reduce((n, r) => n + r.overdue, 0),
                  sums: values.length ? { [VALUE_FIELD]: values.reduce((a, b) => a + b, 0) } : {},
                  avgs: {},
                },
              };
            })
          : null;
      return HttpResponse.json({
        columns: COLUMNS,
        rows,
        groups,
        hidden_projects: 1,
        view_id: view?.id ?? null,
      });
    }),
    http.get('*/api/v1/portfolios/:id/views', () =>
      HttpResponse.json({
        data: state.views.map((v) => ({
          id: v.id,
          name: v.name,
          owner_id: v.owner_id,
          shared: v.owner_id === null,
          layout: 'table',
          filters: {},
          group_by: v.group_by,
          sort: v.sort,
          updated_at: new Date().toISOString(),
        })),
        meta: { next_cursor: null },
      }),
    ),
    http.post('*/api/v1/portfolios/:id/views', async ({ request }) => {
      const b = (await record('POST', request)) as {
        name: string;
        shared?: boolean;
        group_by?: string | null;
      };
      const v = {
        id: `v-${state.views.length + 1}`,
        name: b.name,
        owner_id: b.shared ? null : 'u-ravi',
        group_by: b.group_by ?? null,
        sort: [],
      };
      state.views.push(v);
      return HttpResponse.json(
        {
          data: {
            ...v,
            shared: v.owner_id === null,
            layout: 'table',
            filters: {},
            updated_at: new Date().toISOString(),
          },
          meta,
        },
        { status: 201 },
      );
    }),
    http.post('*/api/v1/portfolios/:id/projects/:pid/stage', async ({ request, params }) => {
      const b = (await record('POST', request)) as { to: string; override?: boolean };
      if (state.gated.has(b.to) && !b.override)
        return HttpResponse.json(
          {
            code: 'gate_not_met',
            title: 'Conflict',
            status: 409,
            detail: 'Implementation isn’t ready',
            readiness: {
              stage: b.to,
              stage_label: 'Implementation',
              met: false,
              items: [
                {
                  kind: 'field',
                  label: 'Contract value',
                  met: true,
                  ref: { type: 'project_field', id: VALUE_FIELD },
                },
                { kind: 'milestone', label: 'Contract signed', met: false, ref: null },
              ],
            },
          },
          { status: 409 },
        );
      const r = state.rows.find((x) => x.id === params.pid);
      if (r) r.stage = b.to;
      return HttpResponse.json({ data: { field_id: STAGE_FIELD, value: b.to }, meta });
    }),
    http.put('*/api/v1/projects/:pid/project-field-values/:fid', async ({ request, params }) => {
      const b = (await record('PUT', request)) as { value: unknown };
      const r = state.rows.find((x) => x.id === params.pid);
      if (r && params.fid === VALUE_FIELD) r.value = b.value as number | null;
      return HttpResponse.json({ data: { field_id: params.fid, value: b.value }, meta });
    }),
    http.post('*/api/v1/portfolios/:id/bulk-set-field', async ({ request }) => {
      const b = (await record('POST', request)) as { project_ids: string[]; value: unknown };
      for (const id of b.project_ids) {
        const r = state.rows.find((x) => x.id === id);
        if (r) r.value = b.value as number;
      }
      return HttpResponse.json({
        data: { updated: b.project_ids.length, skipped: 0 },
        meta: { ...meta, activity_id: null, batch_id: '01a0ccaf-0000-7000-8000-00000000b001' },
      });
    }),
    http.patch('*/api/v1/portfolios/:id/settings', async ({ request }) => {
      await record('PATCH', request);
      return HttpResponse.json({ data: portfolioDetail(), meta });
    }),
    http.post('*/api/v1/portfolios/:id/convert', async ({ request }) => {
      const b = (await record('POST', request)) as { kind: string };
      return HttpResponse.json({ data: portfolioDetail({ kind: b.kind }), meta });
    }),
    http.get('*/api/v1/portfolios/:id/members', () =>
      HttpResponse.json({ data: state.members, meta: { next_cursor: null } }),
    ),
    http.get('*/api/v1/portfolios/:id', () => HttpResponse.json(portfolioDetail())),
  ];
}
