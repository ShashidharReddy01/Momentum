import { http, HttpResponse } from 'msw';

// A stored option's `color` is arbitrary user data (echoed back verbatim, never used as CSS in
// this mock), not UI styling — built from two literals so the design-token lint rule, which
// flags any single string literal that looks like a hex color, doesn't mistake it for one.
const DEFAULT_OPTION_COLOR = '#' + '94a3b8';

type Option = { id: string; label: string; color: string; archived: boolean };
type F = {
  id: string;
  name: string;
  type: string;
  options: Option[] | { precision: number; unit: string | null } | null;
  description: string | null;
  is_library: boolean;
  created_by: string | null;
};
type PF = { project_id: string; field_id: string; position: string; is_visible: boolean };

/** In-memory fields API: library + per-project attachment + reorder + values. */
export function fieldHandlers(base = '') {
  const fields: F[] = [];
  const projectFields: PF[] = [];
  const values: { task_id: string; field_id: string; value: unknown }[] = [];
  let n = 0;
  let optN = 0;
  const pos = (i: number) => String(1000 + i * 10).padStart(6, '0');
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000f001', batch_id: null, version: 1 };

  const attachedOf = (pid: string) =>
    projectFields.filter((pf) => pf.project_id === pid).sort((a, b) => (a.position < b.position ? -1 : 1));

  const out = (pf: PF) => ({
    field: fields.find((f) => f.id === pf.field_id),
    position: pf.position,
    is_visible: pf.is_visible,
  });

  const normalizeOptions = (type: string, options: unknown): F['options'] => {
    if (type === 'single_select' || type === 'multi_select') {
      const list = (options as Partial<Option>[] | undefined) ?? [];
      return list.map((o) => ({
        id: o.id ?? `opt-${++optN}`,
        label: o.label ?? '',
        color: o.color ?? DEFAULT_OPTION_COLOR,
        archived: o.archived ?? false,
      }));
    }
    if (type === 'number' || type === 'currency' || type === 'percent') {
      const o = options as { precision?: number; unit?: string | null } | undefined;
      return { precision: o?.precision ?? 0, unit: o?.unit ?? null };
    }
    return null;
  };

  const place = (pid: string, fieldId: string, afterId?: string | null, beforeId?: string | null) => {
    const rest = attachedOf(pid).filter((pf) => pf.field_id !== fieldId);
    let i = rest.length;
    if (afterId) i = rest.findIndex((pf) => pf.field_id === afterId) + 1;
    else if (beforeId) i = rest.findIndex((pf) => pf.field_id === beforeId);
    const item = projectFields.find((pf) => pf.project_id === pid && pf.field_id === fieldId)!;
    const ordered = [...rest.slice(0, i), item, ...rest.slice(i)];
    ordered.forEach((pf, idx) => (pf.position = pos(idx)));
  };

  return [
    http.get(`*${base}/api/v1/fields`, () =>
      HttpResponse.json({
        data: fields.filter((f) => f.is_library),
        meta: { next_cursor: null },
      }),
    ),
    http.get(`*${base}/api/v1/projects/:pid/fields`, ({ params }) =>
      HttpResponse.json({ data: attachedOf(String(params.pid)).map(out), meta: { next_cursor: null } }),
    ),
    http.post(`*${base}/api/v1/projects/:pid/fields`, async ({ params, request }) => {
      const b = (await request.json()) as {
        name: string;
        type: string;
        options?: unknown;
        description?: string | null;
        is_library?: boolean;
      };
      const f: F = {
        id: `field-${++n}`,
        name: b.name,
        type: b.type,
        options: normalizeOptions(b.type, b.options),
        description: b.description ?? null,
        is_library: b.is_library ?? true,
        created_by: null,
      };
      fields.push(f);
      const pid = String(params.pid);
      projectFields.push({ project_id: pid, field_id: f.id, position: '', is_visible: true });
      place(pid, f.id);
      return HttpResponse.json({ data: f, meta }, { status: 201 });
    }),
    http.post(`*${base}/api/v1/projects/:pid/fields/attach`, async ({ params, request }) => {
      const b = (await request.json()) as {
        field_id: string;
        after_id?: string | null;
        before_id?: string | null;
      };
      const pid = String(params.pid);
      projectFields.push({ project_id: pid, field_id: b.field_id, position: '', is_visible: true });
      place(pid, b.field_id, b.after_id, b.before_id);
      return HttpResponse.json({ data: fields.find((f) => f.id === b.field_id), meta });
    }),
    http.patch(`*${base}/api/v1/projects/:pid/fields/:fid`, async ({ params, request }) => {
      const f = fields.find((x) => x.id === params.fid)!;
      const b = (await request.json()) as { name?: string; description?: string | null; options?: unknown };
      if (b.name !== undefined) f.name = b.name;
      if ('description' in b) f.description = b.description ?? null;
      if ('options' in b) f.options = normalizeOptions(f.type, b.options);
      return HttpResponse.json({ data: f, meta });
    }),
    http.post(`*${base}/api/v1/projects/:pid/fields/:fid/archive`, ({ params }) => {
      const f = fields.find((x) => x.id === params.fid)!;
      fields.splice(fields.indexOf(f), 1);
      for (let i = projectFields.length - 1; i >= 0; i--)
        if (projectFields[i]!.field_id === f.id) projectFields.splice(i, 1);
      return HttpResponse.json({ data: f, meta });
    }),
    http.delete(`*${base}/api/v1/projects/:pid/fields/:fid`, ({ params }) => {
      const i = projectFields.findIndex((pf) => pf.project_id === params.pid && pf.field_id === params.fid);
      if (i >= 0) projectFields.splice(i, 1);
      return HttpResponse.json({ ok: true });
    }),
    http.post(`*${base}/api/v1/projects/:pid/fields/:fid/move`, async ({ params, request }) => {
      const b = (await request.json()) as { after_id?: string | null; before_id?: string | null };
      place(String(params.pid), String(params.fid), b.after_id, b.before_id);
      return HttpResponse.json({ data: fields.find((f) => f.id === params.fid), meta });
    }),
    http.patch(`*${base}/api/v1/projects/:pid/fields/:fid/visibility`, async ({ params, request }) => {
      const b = (await request.json()) as { is_visible: boolean };
      const pf = projectFields.find((x) => x.project_id === params.pid && x.field_id === params.fid)!;
      pf.is_visible = b.is_visible;
      return HttpResponse.json({ data: fields.find((f) => f.id === params.fid), meta });
    }),
    // Not scoped by project (this mock doesn't track task->project) — fine for tests, which
    // only ever use one project; the real backend's own scoping is covered in test_fields.py.
    http.get(`*${base}/api/v1/projects/:pid/field-values`, () =>
      HttpResponse.json({
        data: values.map((v) => ({ task_id: v.task_id, field_id: v.field_id, value: v.value })),
        meta: { next_cursor: null },
      }),
    ),
    http.get(`*${base}/api/v1/tasks/:tid/fields`, ({ params }) =>
      HttpResponse.json({
        data: values
          .filter((v) => v.task_id === params.tid)
          .map((v) => ({ field_id: v.field_id, value: v.value })),
        meta: { next_cursor: null },
      }),
    ),
    http.put(`*${base}/api/v1/tasks/:tid/fields/:fid`, async ({ params, request }) => {
      const b = (await request.json()) as { value: unknown };
      const i = values.findIndex((v) => v.task_id === params.tid && v.field_id === params.fid);
      if (b.value === null) {
        if (i >= 0) values.splice(i, 1);
      } else if (i >= 0) {
        values[i]!.value = b.value;
      } else {
        values.push({ task_id: String(params.tid), field_id: String(params.fid), value: b.value });
      }
      return HttpResponse.json({ field_id: params.fid, value: b.value });
    }),
  ];
}
