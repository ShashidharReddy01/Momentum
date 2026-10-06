import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { MomentumApp } from '@/MomentumApp';
import { authHandlers } from '@/mocks/handlers';
import { teamHandlers } from '@/mocks/teams';
import type { QueryResult } from './queries';
import {
  Aging,
  deltaText,
  Funnel,
  Kpi,
  Note,
  ProjectTable,
  StackedBars,
  StageTime,
  Timeline,
} from './widgets2';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const now = new Date().toISOString();
const result = (extra: Partial<QueryResult>): QueryResult =>
  ({
    kind: 'kpi',
    measure: 'count',
    description: 'Projects · Customer onboarding',
    total: 0,
    tasks_total: 0,
    unestimated: 0,
    groups: [],
    series: [],
    tasks: [],
    more: 0,
    filter_names: [],
    entity: 'projects',
    stacks: [],
    rows: [],
    columns: [],
    stages: [],
    timeline: [],
    notes: [],
    computed_at: now,
    ...extra,
  }) as QueryResult;
const stage = (option_id: string, label: string, extra: object = {}) => ({
  option_id,
  label,
  count: 0,
  buckets: [],
  breaches: 0,
  ...extra,
});

describe('v2 widgets (Phase 7.5)', () => {
  it('a KPI shows the period before and its target', async () => {
    const onDrill = vi.fn();
    render(
      <Kpi
        data={result({ measure: 'throughput', entity: 'stage_events', value: 6, previous: 4, target: 12 })}
        onDrill={onDrill}
      />,
    );
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('projects entered')).toBeInTheDocument();
    expect(screen.getByText(/50% up on the period before \(4\)/)).toHaveClass('text-ok');
    expect(screen.getByText('50% of target')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button'));
    expect(onDrill).toHaveBeenCalledWith({});
    expect(deltaText(3, 3).dir).toBe(0);
    expect(deltaText(2, 0).text).toBe('up from 0 the period before');
  });

  it('a KPI of a currency field and of average progress', () => {
    const { rerender } = render(
      <Kpi
        data={result({ measure: 'sum_project_field', measure_field_name: 'Contract value', value: 108000 })}
        onDrill={() => undefined}
      />,
    );
    expect(screen.getByText('108,000')).toBeInTheDocument();
    expect(screen.getByText('total Contract value')).toBeInTheDocument();
    rerender(<Kpi data={result({ measure: 'avg_progress', value: 0.42 })} onDrill={() => undefined} />);
    expect(screen.getByText('42%')).toBeInTheDocument();
  });

  it('a stacked bar drills into one segment', async () => {
    const onDrill = vi.fn();
    const item = {
      id: 'w',
      kind: 'stacked_bar' as const,
      title: 'RAID',
      spec: {} as never,
      size: 'md' as const,
      version: 1,
    };
    render(
      <StackedBars
        item={item}
        data={result({
          kind: 'stacked_bar',
          entity: 'tasks',
          groups: [{ key: 'p1', label: 'Acme', value: 3, tasks: 3 }],
          stacks: [
            { key: 'high', label: 'High', values: [2] },
            { key: 'low', label: 'Low', values: [1] },
          ],
        })}
        onDrill={onDrill}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Acme, High: 2' }));
    expect(onDrill).toHaveBeenCalledWith({ key: 'p1', splitKey: 'high', label: 'Acme · High' });
    expect(within(screen.getByRole('list', { name: 'RAID: legend' })).getByText('Low')).toBeInTheDocument();
  });

  it('a projects table names field columns and opens a project', async () => {
    const open = vi.fn();
    render(
      <ProjectTable
        data={result({
          kind: 'table',
          columns: ['name', 'status', 'field:f1', 'progress', 'blocked', 'next_milestone'],
          rows: [
            {
              id: 'p1',
              name: 'Acme',
              color: 'proj-1',
              status: 'at_risk',
              'field:f1': 120000,
              progress: 0.5,
              blocked: 2,
              next_milestone: { title: 'Go-live', due_on: '2026-11-02' },
            },
          ],
          more: 3,
        })}
        columnNames={{ 'field:f1': 'Contract value' }}
        onOpenProject={open}
      />,
    );
    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Contract value' })).toBeInTheDocument();
    expect(table).toHaveTextContent('At risk');
    expect(table).toHaveTextContent('120,000');
    expect(table).toHaveTextContent('50%');
    expect(table).toHaveTextContent('Go-live · 2026-11-02');
    expect(screen.getByText('And 3 more.')).toBeInTheDocument();
    await userEvent.click(within(table).getByRole('button', { name: 'Acme' }));
    expect(open).toHaveBeenCalledWith('p1');
  });

  it('a funnel shows conversion and drills into a stage', async () => {
    const onDrill = vi.fn();
    render(
      <Funnel
        data={result({
          kind: 'funnel',
          stages: [
            stage('a', 'Pre-sales', { count: 4 }),
            stage('b', 'Discovery', { count: 3, conversion: 0.75 }),
          ],
        })}
        onDrill={onDrill}
      />,
    );
    expect(screen.getByText(/3 · 75% of the stage before/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Discovery/ }));
    expect(onDrill).toHaveBeenCalledWith({ key: 'b', label: 'Discovery' });
  });

  it('time in stage marks a median past its target', () => {
    render(
      <StageTime
        data={result({
          kind: 'stage_time',
          stages: [
            stage('a', 'Contracts', {
              count: 3,
              median_days: 20,
              p75_days: 25,
              p90_days: 30,
              target_days: 14,
            }),
            stage('b', 'Discovery', { count: 0 }),
          ],
        })}
        onDrill={() => undefined}
      />,
    );
    expect(screen.getByText(/median 20d · p75 25d · p90 30d · target 14d/)).toHaveClass('text-crit');
    expect(screen.getByText('no stays yet')).toBeInTheDocument();
  });

  it('aging lists its buckets and breaches in words', () => {
    render(
      <Aging
        data={result({
          kind: 'aging',
          stages: [
            stage('a', 'Contracts', { count: 2, buckets: [0, 0, 0, 1, 1], breaches: 2, target_days: 14 }),
          ],
        })}
        onDrill={() => undefined}
      />,
    );
    expect(screen.getByText(/2 past the 14d target/)).toBeInTheDocument();
    expect(screen.getByText(/31–60d: 1, 60d\+: 1/)).toBeInTheDocument();
  });

  it('a timeline groups dates by week; a note stays text', async () => {
    const open = vi.fn();
    render(
      <Timeline
        data={result({
          kind: 'timeline',
          timeline: [
            {
              date: '2026-10-07',
              kind: 'milestone',
              title: 'UAT sign-off',
              project_id: 'p1',
              project_name: 'Acme',
            },
            {
              date: '2026-10-21',
              kind: 'go_live',
              title: 'Target go-live',
              project_id: 'p2',
              project_name: 'Beta',
            },
          ],
        })}
        onOpenProject={open}
      />,
    );
    expect(screen.getAllByRole('region')).toHaveLength(2);
    await userEvent.click(screen.getByRole('button', { name: /Beta/ }));
    expect(open).toHaveBeenCalledWith('p2');
    render(<Note text={'<b>bold</b>\n\nSecond paragraph'} />);
    expect(screen.getByText('<b>bold</b>')).toBeInTheDocument();
  });
});

// ---------------- the page: filters, pins, the drill, templates ----------------

const widget = (id: string, kind: string, title: string, query_spec: object, size = 'md') => ({
  id,
  kind,
  title,
  query_spec,
  viz: { size },
  version: 1,
});
const FILTERS = {
  portfolio_id: null,
  period: null,
  period_from: null,
  period_to: null,
  owner: [],
  assignee: [],
  fields: [],
};
const DETAIL = {
  id: 'd2',
  name: 'Implementation lead',
  description: null,
  scope: 'workspace',
  project_id: null,
  owner_id: 'u1',
  version: 1,
  can_edit: true,
  widget_count: 2,
  created_at: now,
  updated_at: now,
  filters: { ...FILTERS, portfolio_id: 'f1' },
  portfolio_id: null,
  template: 'implementation_lead',
  pinned: false,
  widgets: [
    widget('w-kpi', 'kpi', 'Slipping', { version: 2, entity: 'projects', filters: { slipping: true } }, 'sm'),
    widget('w-funnel', 'funnel', 'Lifecycle funnel', {
      version: 2,
      entity: 'stage_events',
      portfolio_id: 'f1',
      analysis: 'funnel',
    }),
  ],
};
const DATA: Record<string, QueryResult> = {
  'w-kpi': result({ value: 5, total: 5 }),
  'w-funnel': result({
    kind: 'funnel',
    entity: 'stage_events',
    stages: [stage('s1', 'Pre-sales', { count: 4 }), stage('s2', 'Discovery', { count: 2, conversion: 0.5 })],
  }),
};

function boot() {
  const dataCalls: string[] = [];
  const drills: Record<string, unknown>[] = [];
  const patches: Record<string, unknown>[] = [];
  const pins: string[] = [];
  const created: Record<string, unknown>[] = [];
  server.use(
    ...authHandlers({ loggedIn: true }).handlers,
    ...teamHandlers(),
    http.get('*/api/v1/project-fields', () => HttpResponse.json({ data: [] })),
    http.get('*/api/v1/portfolios', () =>
      HttpResponse.json({ data: [{ id: 'f1', name: 'Customer onboarding', stage_field_id: 'sf' }] }),
    ),
    http.get('*/api/v1/dashboards', () => HttpResponse.json({ data: [DETAIL] })),
    http.get('*/api/v1/dashboards/pinned', () => HttpResponse.json({ data: [] })),
    http.get('*/api/v1/dashboards/templates', () =>
      HttpResponse.json({
        data: [
          {
            key: 'sales',
            name: 'Sales',
            description: 'Your pipeline',
            persona: 'Sales AE',
            widgets: ['My pipeline value', 'Deal aging'],
          },
        ],
      }),
    ),
    http.post('*/api/v1/dashboards/from-template/preview', () =>
      HttpResponse.json({
        template: 'sales',
        name: 'Sales',
        description: 'Your pipeline',
        filters: FILTERS,
        widgets: [
          {
            kind: 'kpi',
            title: 'My pipeline value',
            query_spec: { version: 2, entity: 'projects' },
            viz: { size: 'sm' },
          },
        ],
        notes: ['Dropped "My accounts": no project field named "Target go-live".'],
      }),
    ),
    http.post('*/api/v1/dashboards/from-template', async ({ request }) => {
      created.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(
        {
          data: { dashboard: { ...DETAIL, id: 'd3', name: 'Sales' }, notes: [] },
          meta: { activity_id: '01a0ccaf-0000-7000-8000-00000000e009', batch_id: null, version: 1 },
        },
        { status: 201 },
      );
    }),
    http.get('*/api/v1/dashboards/:id', () => HttpResponse.json(DETAIL)),
    http.get('*/api/v1/dashboards/widgets/:wid/data', ({ params, request }) => {
      dataCalls.push(new URL(request.url).searchParams.get('filters') ?? '');
      return HttpResponse.json(DATA[params.wid as string]);
    }),
    http.post('*/api/v1/dashboards/drill', async ({ request }) => {
      drills.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({
        label: 'Discovery',
        total: 1,
        tasks: [],
        entity: 'projects',
        projects: [{ id: 'p1', name: 'Acme Corp', stage: 'Discovery', owner_name: 'Ravi Kumar' }],
      });
    }),
    http.patch('*/api/v1/dashboards/:id', async ({ request }) => {
      patches.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({
        data: DETAIL,
        meta: { activity_id: '01a0ccaf-0000-7000-8000-00000000e010', batch_id: null, version: 2 },
      });
    }),
    http.put('*/api/v1/dashboards/:id/pin', ({ params }) => {
      pins.push(`pin ${params.id as string}`);
      return HttpResponse.json({ ok: true });
    }),
  );
  return { dataCalls, drills, patches, pins, created, user: userEvent.setup() };
}

describe('Dashboards v2 page (Phase 7.5)', () => {
  it('a stage drill lists the projects behind it', async () => {
    const { drills, user } = boot();
    window.history.replaceState(null, '', '/dashboards/d2');
    render(<MomentumApp />);
    const card = await screen.findByRole('region', { name: 'Lifecycle funnel' });
    await user.click(await within(card).findByRole('button', { name: /Discovery/ }));
    const panel = await screen.findByRole('complementary', { name: 'Projects behind this number' });
    expect(await within(panel).findByRole('link', { name: /Acme Corp/ })).toHaveAttribute(
      'href',
      '/projects/p1',
    );
    expect(drills[0]).toMatchObject({ key: 's2', query_spec: { entity: 'stage_events' } });
  });

  it('filters change the view for me, and an editor saves them for everyone', async () => {
    const { dataCalls, patches, user } = boot();
    window.history.replaceState(null, '', '/dashboards/d2');
    render(<MomentumApp />);
    const bar = await screen.findByRole('region', { name: 'Dashboard filters' });
    await screen.findByRole('region', { name: 'Slipping' });
    await user.click(within(bar).getByRole('button', { name: 'Assigned to me' }));
    await waitFor(() => expect(dataCalls.some((f) => f.includes('"assignee":["me"]'))).toBe(true));
    expect(dataCalls.find((f) => f.includes('assignee'))).toContain('"portfolio_id":"f1"');
    expect(within(bar).getByText('Only you see this view')).toBeInTheDocument();
    await user.click(within(bar).getByRole('button', { name: 'Save for everyone' }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ filters: { portfolio_id: 'f1', assignee: ['me'] } });
  });

  it('pins a dashboard to Home', async () => {
    const { pins, user } = boot();
    window.history.replaceState(null, '', '/dashboards/d2');
    render(<MomentumApp />);
    await user.click(await screen.findByRole('button', { name: 'Pin to Home' }));
    await waitFor(() => expect(pins).toEqual(['pin d2']));
  });

  it('a template preview says what it leaves out before creating', async () => {
    const { created, user } = boot();
    window.history.replaceState(null, '', '/dashboards');
    render(<MomentumApp />);
    await user.click(await screen.findByRole('button', { name: 'From a template' }));
    const dialog = await screen.findByRole('dialog', { name: 'New dashboard from a template' });
    await user.click(await within(dialog).findByRole('button', { name: /Sales/ }));
    await user.selectOptions(within(dialog).getByLabelText('Portfolio'), 'f1');
    expect(await within(dialog).findByText('My pipeline value')).toBeInTheDocument();
    expect(within(dialog).getByText(/no project field named "Target go-live"/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Create dashboard' }));
    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({ template: 'sales', portfolio_id: 'f1', portfolio_tab: false });
  });
});
