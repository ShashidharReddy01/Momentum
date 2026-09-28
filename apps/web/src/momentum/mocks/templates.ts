import { http, HttpResponse } from 'msw';

type T = {
  id: string;
  project_id: string | null;
  kind: string;
  name: string;
  description: string | null;
  payload: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
};

/** In-memory S4.3.1/S4.3.2 templates API, for component tests. */
export function templateHandlers(base = '') {
  const templates: T[] = [];
  let n = 0;
  const now = '2026-09-28T00:00:00Z';

  return [
    http.get(`*${base}/api/v1/templates`, ({ request }) => {
      const url = new URL(request.url);
      const kind = url.searchParams.get('kind') ?? 'project';
      const projectId = url.searchParams.get('project_id');
      const rows = templates.filter(
        (t) => t.kind === kind && (projectId === null || t.project_id === projectId),
      );
      return HttpResponse.json({ data: rows, meta: { next_cursor: null } });
    }),
    http.post(`*${base}/api/v1/templates/from-project`, async ({ request }) => {
      const b = (await request.json()) as { project_id: string; name: string; description?: string };
      const t: T = {
        id: `tpl-${++n}`,
        project_id: null,
        kind: 'project',
        name: b.name,
        description: b.description ?? null,
        payload: { roles: [], fields: [], sections: [], rules: [] },
        created_by: 'user-1',
        created_at: now,
        updated_at: now,
      };
      templates.push(t);
      return HttpResponse.json(
        { data: t, meta: { activity_id: null, batch_id: null, version: 1 } },
        { status: 201 },
      );
    }),
    http.post(`*${base}/api/v1/templates/from-task`, async ({ request }) => {
      const b = (await request.json()) as {
        project_id: string;
        name: string;
        title: string;
        description?: string;
        subtasks?: string[];
        field_values?: Record<string, unknown>;
      };
      const t: T = {
        id: `tpl-${++n}`,
        project_id: b.project_id,
        kind: 'task',
        name: b.name,
        description: null,
        payload: {
          title: b.title,
          description: b.description ?? null,
          subtasks: b.subtasks ?? [],
          field_values: b.field_values ?? {},
        },
        created_by: 'user-1',
        created_at: now,
        updated_at: now,
      };
      templates.push(t);
      return HttpResponse.json(
        { data: t, meta: { activity_id: null, batch_id: null, version: 1 } },
        { status: 201 },
      );
    }),
    http.delete(`*${base}/api/v1/templates/:id`, ({ params }) => {
      const i = templates.findIndex((t) => t.id === params.id);
      if (i >= 0) templates.splice(i, 1);
      return HttpResponse.json({ ok: true });
    }),
    http.post(`*${base}/api/v1/ai/templates/from-brief`, async ({ request }) => {
      const b = (await request.json()) as { brief: string };
      return HttpResponse.json({
        name: 'Drafted process',
        description: `Drafted from: ${b.brief}`,
        sections: [{ name: 'Step one', tasks: [{ title: 'Do the first thing', subtasks: [] }] }],
      });
    }),
    http.post(`*${base}/api/v1/ai/templates/from-brief/save`, async ({ request }) => {
      const b = (await request.json()) as { name: string; description?: string | null };
      const t: T = {
        id: `tpl-${++n}`,
        project_id: null,
        kind: 'project',
        name: b.name,
        description: b.description ?? null,
        payload: { roles: [], fields: [], sections: [], rules: [] },
        created_by: 'user-1',
        created_at: now,
        updated_at: now,
      };
      templates.push(t);
      return HttpResponse.json({ data: t, meta: { activity_id: null, batch_id: null, version: 1 } });
    }),
    http.post(`*${base}/api/v1/templates/:id/new-task`, ({ params }) => {
      const t = templates.find((x) => x.id === params.id);
      const payload = (t?.payload ?? {}) as { title?: string };
      return HttpResponse.json(
        {
          data: {
            id: 'task-new',
            title: payload.title ?? 'Untitled',
            completed_at: null,
          },
          meta: { activity_id: null, batch_id: null, version: 1 },
        },
        { status: 201 },
      );
    }),
  ];
}
