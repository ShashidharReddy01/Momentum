import { http, HttpResponse } from 'msw';
import type { components } from '@/lib/api/schema';

type RecordDetail = components['schemas']['RecordDetailOut'];
type RecordType = components['schemas']['RecordTypeOut'];
type Entity = components['schemas']['EntityOut'];
type Skill = components['schemas']['SkillOut'];

/** Phase 7.6 S76-08: a synthetic bill type (the shape pydantic writes, with `$defs`). */
export function billTypeFixture(over: Partial<RecordType> = {}): RecordType {
  return {
    key: 'echo_bill',
    version: 1,
    label: 'Echo bill',
    classification: 'financial',
    count: 2,
    schema: {
      title: 'EchoBill',
      type: 'object',
      $defs: {
        Vendor: {
          type: 'object',
          properties: {
            name: { type: 'string', title: 'Name' },
            entity_id: { anyOf: [{ type: 'string' }, { type: 'null' }] },
          },
          required: ['name'],
        },
        Line: {
          type: 'object',
          properties: {
            description: { type: 'string', title: 'Description' },
            amount: { anyOf: [{ type: 'number' }, { type: 'string' }], title: 'Amount' },
          },
          required: ['description', 'amount'],
        },
      },
      properties: {
        vendor: { $ref: '#/$defs/Vendor' },
        number: { type: 'string', title: 'Number' },
        total: { anyOf: [{ type: 'number' }, { type: 'string' }], title: 'Total' },
        currency: { type: 'string', title: 'Currency' },
        dated: { type: 'string', format: 'date', title: 'Dated' },
        lines: { type: 'array', items: { $ref: '#/$defs/Line' }, title: 'Lines' },
      },
      required: ['vendor', 'number', 'total', 'currency', 'dated'],
    },
    display: {
      title: '{vendor.name} {number}',
      money: ['total', 'lines[].amount'],
      currency_field: 'currency',
      dates: ['dated'],
      arrays: { lines: 'Lines' },
      columns: ['vendor.name', 'number', 'dated', 'total', 'currency'],
    },
    ...over,
  };
}

export function recordFixture(over: Partial<RecordDetail> = {}): RecordDetail {
  return {
    id: 'rec-1',
    type: 'echo_bill',
    type_version: 1,
    type_label: 'Echo bill',
    classification: 'financial',
    project_id: 'p-1',
    task_id: 't-1',
    source_attachment_id: 'att-1',
    source_locator: null,
    run_id: 'run-9',
    status: 'needs_review',
    title: 'Acme Ltd INV-0041',
    data: {
      vendor: { name: 'Acme Ltd' },
      number: 'INV-0041',
      total: '100.00',
      currency: 'USD',
      dated: '2026-09-15',
      lines: [
        { description: 'Widgets', amount: '60.00' },
        { description: 'Gadgets', amount: '40.00' },
      ],
    },
    provenance: {
      number: { method: 'text', page: 1, bbox: [450, 40, 560, 60], text: 'INV-0041', confidence: 0.98 },
      total: { method: 'text', page: 1, bbox: [470, 700, 560, 720], confidence: 0.95 },
      'lines[0].amount': { method: 'table', page: 1, bbox: [470, 300, 560, 316] },
    },
    checks: [
      {
        id: 'lines_add_up',
        severity: 'block',
        passed: true,
        title: 'Lines add up to the total',
        fields: ['total', 'lines'],
      },
      {
        id: 'po_found',
        severity: 'warn',
        passed: false,
        title: 'No purchase order found',
        detail: 'PO-77 is unknown',
        fields: ['number'],
      },
    ],
    decision: { decision: 'needs_person', reason: 'No purchase order matched' },
    confidence: '0.91',
    amount: '100.00',
    currency: 'USD',
    occurred_on: '2026-09-15',
    entity_ids: ['ent-1'],
    version: 2,
    created_via: 'agent',
    created_at: '2026-10-08T10:00:00Z',
    updated_at: '2026-10-08T10:05:00Z',
    versions: [
      {
        version: 2,
        status: 'needs_review',
        changed_by: 'u-1',
        via: 'review',
        change: { ops: [{ op: 'set', path: 'dated', value: '2026-09-15' }], fields: ['dated'] },
        reason: null,
        created_at: '2026-10-08T10:05:00Z',
      },
      {
        version: 1,
        status: 'needs_review',
        changed_by: null,
        via: 'agent',
        change: {},
        reason: null,
        created_at: '2026-10-08T10:00:00Z',
      },
    ],
    duplicates: [],
    can_edit: true,
    can_decide: true,
    decide_blocked: null,
    ...over,
  };
}

export function entityFixture(over: Partial<Entity> = {}): Entity {
  return {
    id: 'ent-1',
    type: 'vendor',
    key: 'acme ltd',
    name: 'Acme Ltd',
    aliases: ['ACME Limited'],
    attributes: { bank: { last4: '4821', display: '•••• 4821' } },
    profile: { records: 2, median_total: '100.00' },
    status: 'active',
    merged_into: null,
    created_via: 'agent',
    version: 1,
    created_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
    ...over,
  };
}

export function skillFixture(over: Partial<Skill> = {}): Skill {
  return {
    id: 'sk-1',
    pack_key: 'echo',
    scope_type: 'entity',
    scope_id: 'ent-1',
    kind: 'hint',
    field: 'number',
    content: { text: 'Acme puts the invoice number top right, after "Ref".' },
    status: 'proposed',
    version: 1,
    supersedes_id: null,
    source: 'learned',
    provenance: { record_id: 'rec-1', task_id: 't-1', ops_summary: 'number corrected' },
    tryout: { status: 'done', before: { wrong: 3 }, after: { wrong: 0 }, regressions: [] },
    metrics: {},
    may_be_hurting: false,
    decided_by: null,
    decided_at: null,
    decision_note: null,
    created_at: '2026-10-08T10:00:00Z',
    ...over,
  };
}

/** Records, their types, source, entities and skills; saves and decisions are recorded. */
export function recordHandlers(
  opts: {
    record?: RecordDetail;
    list?: RecordDetail[];
    types?: RecordType[];
    conflictOnce?: boolean;
    skills?: Skill[];
  } = {},
) {
  let record = opts.record ?? recordFixture();
  const list = opts.list ?? [
    record,
    recordFixture({
      id: 'rec-2',
      title: 'Globex G-7',
      data: {
        vendor: { name: 'Globex' },
        number: 'G-7',
        total: '450.50',
        currency: 'USD',
        dated: '2026-10-04',
        lines: [],
      },
      status: 'ready',
    }),
  ];
  const types = opts.types ?? [billTypeFixture()];
  let conflict = opts.conflictOnce ?? false;
  const patches: unknown[] = [];
  const bulk: unknown[] = [];
  const queries: unknown[] = [];
  const decisions: { id: string; decision: string; body: unknown }[] = [];
  const listQueries: URLSearchParams[] = [];
  const skills = opts.skills ?? [
    skillFixture(),
    skillFixture({
      id: 'sk-2',
      status: 'active',
      metrics: { uses: 12, helped: 3, hurt: 7 },
      may_be_hurting: true,
      kind: 'rule',
      content: { min_total: 10 },
    }),
  ];
  const handlers = [
    http.get('*/api/v1/records/types', () => HttpResponse.json({ data: types, meta: { next_cursor: null } })),
    http.post('*/api/v1/records/status', async ({ request }) => {
      const body = (await request.json()) as { ids: string[] };
      bulk.push(body);
      return HttpResponse.json({ updated: body.ids.length, skipped: [], batch_id: 'batch-1' });
    }),
    http.post('*/api/v1/records/query', async ({ request }) => {
      queries.push(await request.json());
      return HttpResponse.json({
        type: 'echo_bill',
        rows: [
          { group: {}, values: { count: 2, 'sum(amount)': 550.5 }, value: 2, currency: 'USD' },
          { group: {}, values: { count: 1, 'sum(amount)': 800 }, value: 1, currency: 'EUR' },
        ],
        matched: 3,
        scanned: 3,
        truncated: false,
        measures: ['count', 'sum(amount)'],
        group_by: [],
        notes: ['Amounts are per currency; different currencies are never added together'],
      });
    }),
    http.get('*/api/v1/records', ({ request }) => {
      const q = new URL(request.url).searchParams;
      listQueries.push(q);
      const data = list.filter(
        (r) =>
          (!q.get('task_id') || r.task_id === q.get('task_id')) &&
          (!q.getAll('status').length || q.getAll('status').includes(r.status)) &&
          (!q.get('q') || r.title.toLowerCase().includes(q.get('q')!.toLowerCase())),
      );
      return HttpResponse.json({ data, meta: { next_cursor: null } });
    }),
    http.get('*/api/v1/records/:id/source', () =>
      HttpResponse.json({
        attachment_id: 'att-1',
        filename: 'acme-inv-0041.pdf',
        mime: 'application/pdf',
        locator: null,
        pages: [
          { n: 1, width: 612, height: 792 },
          { n: 2, width: 612, height: 792 },
        ],
      }),
    ),
    http.get('*/api/v1/records/:id', () => HttpResponse.json(record)),
    http.patch('*/api/v1/records/:id', async ({ request }) => {
      const body = (await request.json()) as {
        ops: { op: string; path?: string; value?: unknown; status?: string }[];
        expected_version: number;
      };
      patches.push(body);
      if (conflict) {
        conflict = false;
        record = { ...record, version: record.version + 1 };
        return HttpResponse.json(
          { code: 'version_conflict', title: 'Conflict', detail: 'This record was changed by someone else' },
          { status: 409 },
        );
      }
      const data = structuredClone(record.data) as Record<string, unknown>;
      let status = record.status;
      for (const op of body.ops) {
        if (op.op === 'set' && op.path && !op.path.includes('.') && !op.path.includes('['))
          data[op.path] = op.value;
        if (op.op === 'set_status' && op.status) status = op.status;
      }
      record = { ...record, data, status, version: record.version + 1 };
      return HttpResponse.json({ ...record, activity_id: 'act-rec' });
    }),
    http.get('*/api/v1/entities', () =>
      HttpResponse.json({
        data: [entityFixture(), entityFixture({ id: 'ent-2', name: 'Globex', key: 'globex', aliases: [] })],
        meta: { next_cursor: null },
      }),
    ),
    http.get('*/api/v1/entities/:id/activity', () =>
      HttpResponse.json({
        data: [
          {
            id: 'a2',
            verb: 'entity.updated',
            actor_id: 'u-1',
            actor_kind: 'user',
            diff: {},
            created_at: '2026-10-02T10:00:00Z',
          },
          {
            id: 'a1',
            verb: 'entity.created',
            actor_id: null,
            actor_kind: 'agent',
            diff: {},
            created_at: '2026-10-01T10:00:00Z',
          },
        ],
        meta: { next_cursor: null },
      }),
    ),
    http.get('*/api/v1/entities/:id', ({ params }) =>
      HttpResponse.json(entityFixture({ id: String(params.id) })),
    ),
    http.get('*/api/v1/skills', ({ request }) => {
      const st = new URL(request.url).searchParams.get('status');
      return HttpResponse.json({
        data: skills.filter((s) => !st || s.status === st),
        meta: { next_cursor: null },
      });
    }),
    http.post('*/api/v1/skills/:id/:decision', async ({ params, request }) => {
      const body = await request.json();
      decisions.push({ id: String(params.id), decision: String(params.decision), body });
      const s = skills.find((x) => x.id === params.id)!;
      return HttpResponse.json({
        ...s,
        status:
          params.decision === 'approve' ? 'active' : params.decision === 'reject' ? 'rejected' : 'retired',
      });
    }),
  ];
  return { handlers, patches, bulk, queries, decisions, listQueries };
}
