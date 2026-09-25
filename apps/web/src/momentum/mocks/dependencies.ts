import { http, HttpResponse } from 'msw';

type Dep = { task_id: string; depends_on_id: string };
type TaskInfo = { id: string; title: string; completed_at: string | null };

/** In-memory S2.4.2 dependencies API. Independent of `mocks/tasks.ts`'s own store — seeded with
 * `tasks` (id/title/completed_at, used to render blocker/blocking rows and the search picker)
 * and `initial` edges. */
export function dependencyHandlers(base = '', tasks: TaskInfo[] = [], initial: Dep[] = []) {
  const deps: Dep[] = [...initial];
  const taskOf = (id: string) => tasks.find((t) => t.id === id);
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000f201', batch_id: null, version: 1 };
  const summary = (t: TaskInfo) => ({
    id: t.id,
    key: `T-${t.id}`,
    title: t.title,
    completed_at: t.completed_at,
  });

  return [
    http.get(`*${base}/api/v1/tasks/:tid/dependencies`, ({ params }) => {
      const blockedBy = deps
        .filter((d) => d.task_id === params.tid)
        .map((d) => taskOf(d.depends_on_id))
        .filter((t): t is TaskInfo => !!t);
      const blocking = deps
        .filter((d) => d.depends_on_id === params.tid)
        .map((d) => taskOf(d.task_id))
        .filter((t): t is TaskInfo => !!t);
      return HttpResponse.json({
        blocked_by: blockedBy.map(summary),
        blocking: blocking.map(summary),
      });
    }),
    http.post(`*${base}/api/v1/tasks/:tid/dependencies`, async ({ params, request }) => {
      const taskId = String(params.tid);
      const b = (await request.json()) as { depends_on_id: string };
      if (taskId === b.depends_on_id)
        return HttpResponse.json({ code: 'self', detail: 'self' }, { status: 422 });
      if (deps.some((d) => d.task_id === taskId && d.depends_on_id === b.depends_on_id))
        return HttpResponse.json({ code: 'already_exists', detail: 'exists' }, { status: 409 });
      deps.push({ task_id: taskId, depends_on_id: b.depends_on_id });
      const blocker = taskOf(b.depends_on_id);
      return HttpResponse.json({ data: blocker ? summary(blocker) : null, meta }, { status: 201 });
    }),
    http.delete(`*${base}/api/v1/tasks/:tid/dependencies/:dep`, ({ params }) => {
      const i = deps.findIndex((d) => d.task_id === params.tid && d.depends_on_id === params.dep);
      if (i >= 0) deps.splice(i, 1);
      return HttpResponse.json({ data: { ok: true }, meta });
    }),
    http.get(`*${base}/api/v1/projects/:pid/blocked-tasks`, () => {
      const blocked = new Set(
        deps
          .filter((d) => {
            const blocker = taskOf(d.depends_on_id);
            return blocker && !blocker.completed_at;
          })
          .map((d) => d.task_id),
      );
      return HttpResponse.json({
        data: [...blocked].map((task_id) => ({ task_id })),
        meta: { next_cursor: null },
      });
    }),
    http.get(`*${base}/api/v1/projects/:pid/tasks/search`, ({ request }) => {
      const url = new URL(request.url);
      const q = (url.searchParams.get('q') ?? '').toLowerCase();
      const exclude = url.searchParams.get('exclude');
      const rows = tasks.filter((t) => t.id !== exclude && (!q || t.title.toLowerCase().includes(q)));
      return HttpResponse.json({ data: rows.map(summary), meta: { next_cursor: null } });
    }),
    http.post(`*${base}/api/v1/tasks/:tid/complete`, ({ params, request }) => {
      const url = new URL(request.url);
      const force = url.searchParams.get('force') === 'true';
      const t = taskOf(String(params.tid));
      if (
        !force &&
        deps.some((d) => {
          if (d.task_id !== params.tid) return false;
          const blocker = taskOf(d.depends_on_id);
          return blocker && !blocker.completed_at;
        })
      ) {
        return HttpResponse.json({ code: 'has_incomplete_blockers', detail: 'blocked' }, { status: 409 });
      }
      if (t) t.completed_at = new Date().toISOString();
      return HttpResponse.json({
        data: { id: params.tid, completed_at: t?.completed_at ?? new Date().toISOString() },
        meta,
      });
    }),
  ];
}
