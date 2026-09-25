import { http, HttpResponse } from 'msw';

type ProjectRef = { id: string; name: string; color: string | null };
type Placement = { task_id: string; project_id: string; section_id: string; position: string };

/** In-memory S2.4.1 multi-homing API: task<->project placements, the bulk per-project
 * "other-placements" endpoint, and add/remove. Independent of `mocks/tasks.ts`'s own store (that
 * mock only tracks one project/section per task) — seeded with `projects` (id/name/color, used
 * for both the "add to project" picker and chip rendering) and `initial` placements. */
export function multiHomingHandlers(base = '', projects: ProjectRef[] = [], initial: Placement[] = []) {
  const placements: Placement[] = [...initial];
  const projectOf = (id: string) => projects.find((p) => p.id === id);
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000e001', batch_id: null, version: 1 };

  const out = (p: Placement) => ({
    project: projectOf(p.project_id),
    section: { id: p.section_id, name: 'To do' },
    position: p.position,
  });

  return [
    http.get(`*${base}/api/v1/tasks/:tid/projects`, ({ params }) =>
      HttpResponse.json({
        data: placements.filter((p) => p.task_id === params.tid).map(out),
        meta: { next_cursor: null },
      }),
    ),
    http.post(`*${base}/api/v1/tasks/:tid/projects`, async ({ params, request }) => {
      const taskId = String(params.tid);
      const b = (await request.json()) as { project_id: string; section_id?: string | null };
      if (placements.some((p) => p.task_id === taskId && p.project_id === b.project_id))
        return HttpResponse.json({ detail: 'already placed' }, { status: 409 });
      const p: Placement = {
        task_id: taskId,
        project_id: b.project_id,
        section_id: b.section_id ?? `${b.project_id}-s1`,
        position: '500000',
      };
      placements.push(p);
      return HttpResponse.json({ data: out(p), meta }, { status: 201 });
    }),
    http.delete(`*${base}/api/v1/tasks/:tid/projects/:pid`, ({ params }) => {
      const taskId = String(params.tid);
      const remaining = placements.filter((p) => p.task_id === taskId);
      if (remaining.length <= 1) return HttpResponse.json({ detail: 'last placement' }, { status: 422 });
      const i = placements.findIndex((p) => p.task_id === taskId && p.project_id === params.pid);
      if (i >= 0) placements.splice(i, 1);
      return HttpResponse.json({ data: { ok: true }, meta });
    }),
    http.get(`*${base}/api/v1/projects/:pid/other-placements`, ({ params }) => {
      const inThisProject = new Set(
        placements.filter((p) => p.project_id === params.pid).map((p) => p.task_id),
      );
      const rows = placements
        .filter((p) => p.project_id !== params.pid && inThisProject.has(p.task_id))
        .map((p) => ({ task_id: p.task_id, project: projectOf(p.project_id) }));
      return HttpResponse.json({ data: rows, meta: { next_cursor: null } });
    }),
  ];
}
