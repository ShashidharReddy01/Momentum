import { http, HttpResponse } from 'msw';

const DEFAULT_TAG_COLOR = '#' + '94a3b8';

type T = { id: string; name: string; color: string };

/** In-memory tags API: workspace library, task attach/detach, bulk per-project, and the tag page.
 * Not scoped by project (this mock doesn't track task->project) — fine for tests, which only ever
 * use one project; the real backend's own scoping is covered in test_tags.py. */
export function tagHandlers(base = '') {
  const tags: T[] = [];
  const taskTags: { task_id: string; tag_id: string }[] = [];
  const tasksById = new Map<string, Record<string, unknown>>();
  let n = 0;
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000f101', batch_id: null, version: 1 };

  const findByName = (name: string) => tags.find((t) => t.name.toLowerCase() === name.toLowerCase());

  return [
    http.get(`*${base}/api/v1/tags`, () =>
      HttpResponse.json({ data: [...tags].sort((a, b) => a.name.localeCompare(b.name)), meta: {} }),
    ),
    http.post(`*${base}/api/v1/tags`, async ({ request }) => {
      const b = (await request.json()) as { name: string; color?: string };
      if (findByName(b.name)) return HttpResponse.json({ detail: 'duplicate' }, { status: 409 });
      const t: T = { id: `tag-${++n}`, name: b.name, color: b.color ?? DEFAULT_TAG_COLOR };
      tags.push(t);
      return HttpResponse.json({ data: t, meta }, { status: 201 });
    }),
    http.patch(`*${base}/api/v1/tags/:id`, async ({ params, request }) => {
      const t = tags.find((x) => x.id === params.id)!;
      const b = (await request.json()) as { name?: string; color?: string };
      if (b.name !== undefined) t.name = b.name;
      if (b.color !== undefined) t.color = b.color;
      return HttpResponse.json({ data: t, meta });
    }),
    http.delete(`*${base}/api/v1/tags/:id`, ({ params }) => {
      const i = tags.findIndex((t) => t.id === params.id);
      if (i >= 0) tags.splice(i, 1);
      return HttpResponse.json({ ok: true });
    }),
    http.get(`*${base}/api/v1/tags/:id/tasks`, ({ params }) => {
      const ids = new Set(taskTags.filter((tt) => tt.tag_id === params.id).map((tt) => tt.task_id));
      const rows = [...ids].map((id) => tasksById.get(id)).filter(Boolean);
      return HttpResponse.json({ data: rows, meta: { next_cursor: null } });
    }),
    http.get(`*${base}/api/v1/projects/:pid/task-tags`, () =>
      HttpResponse.json({
        data: taskTags.map((tt) => ({ task_id: tt.task_id, tag: tags.find((t) => t.id === tt.tag_id) })),
        meta: { next_cursor: null },
      }),
    ),
    http.get(`*${base}/api/v1/tasks/:tid/tags`, ({ params }) => {
      const ids = taskTags.filter((tt) => tt.task_id === params.tid).map((tt) => tt.tag_id);
      return HttpResponse.json({ data: tags.filter((t) => ids.includes(t.id)), meta: { next_cursor: null } });
    }),
    http.post(`*${base}/api/v1/tasks/:tid/tags`, async ({ params, request }) => {
      const taskId = String(params.tid);
      const b = (await request.json()) as { tag_id?: string | null; name?: string | null };
      let tag = b.tag_id ? tags.find((t) => t.id === b.tag_id) : b.name ? findByName(b.name) : undefined;
      if (!tag && b.name) {
        tag = { id: `tag-${++n}`, name: b.name, color: DEFAULT_TAG_COLOR };
        tags.push(tag);
      }
      if (!tag) return HttpResponse.json({ detail: 'not found' }, { status: 404 });
      if (!tasksById.has(taskId)) tasksById.set(taskId, { id: taskId, title: 'Task', due_on: null });
      if (!taskTags.some((tt) => tt.task_id === taskId && tt.tag_id === tag!.id))
        taskTags.push({ task_id: taskId, tag_id: tag.id });
      return HttpResponse.json({ data: tag, meta }, { status: 201 });
    }),
    http.delete(`*${base}/api/v1/tasks/:tid/tags/:tagId`, ({ params }) => {
      const i = taskTags.findIndex((tt) => tt.task_id === params.tid && tt.tag_id === params.tagId);
      if (i >= 0) taskTags.splice(i, 1);
      return HttpResponse.json({ ok: true });
    }),
  ];
}
