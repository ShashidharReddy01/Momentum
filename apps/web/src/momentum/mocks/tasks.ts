import { delay, http, HttpResponse } from 'msw';

type T = {
  id: string;
  number: number;
  key: string;
  title: string;
  type: string;
  project_id: string;
  section_id: string;
  position: string;
  assignee_id: string | null;
  start_on: string | null;
  due_on: string | null;
  due_at: string | null;
  completed_at: string | null;
  parent_id: null;
  priority: null;
  version: number;
  created_at: string;
};

/** In-memory tasks API with a small network delay (exercises optimistic UI and the create queue). */
export function taskHandlers(
  base = '',
  initial: Record<string, Record<string, string[]>> = {},
  latency = 15,
) {
  const tasks: T[] = [];
  let n = 0;
  const pos = (i: number) => String(100000 + i * 100).padStart(8, '0');
  const make = (pid: string, sid: string, title: string, position: string): T => {
    n += 1;
    return {
      id: `task-${n}`,
      number: n,
      key: `T-${n}`,
      title,
      type: 'task',
      project_id: pid,
      section_id: sid,
      position,
      assignee_id: null,
      start_on: null,
      due_on: null,
      due_at: null,
      completed_at: null,
      parent_id: null,
      priority: null,
      version: 1,
      created_at: new Date().toISOString(),
    };
  };
  for (const [pid, sections] of Object.entries(initial)) {
    for (const [sid, titles] of Object.entries(sections)) {
      titles.forEach((title, i) => tasks.push(make(pid, sid, title, pos(i))));
    }
  }
  const inSection = (sid: string) =>
    tasks.filter((t) => t.section_id === sid).sort((a, b) => (a.position < b.position ? -1 : 1));
  const renumber = (ordered: T[]) => ordered.forEach((t, i) => (t.position = pos(i)));
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000d001', batch_id: null, version: 1 };
  const place = (t: T, afterId?: string | null) => {
    const rest = inSection(t.section_id).filter((x) => x.id !== t.id);
    const i = afterId ? rest.findIndex((x) => x.id === afterId) + 1 : rest.length;
    renumber([...rest.slice(0, i), t, ...rest.slice(i)]);
  };
  return [
    http.get(`*${base}/api/v1/projects/:pid/tasks`, ({ params, request }) => {
      const completed = new URL(request.url).searchParams.get('completed') === 'true';
      const data = tasks
        .filter((t) => t.project_id === params.pid && !!t.completed_at === completed)
        .sort((a, b) => (a.section_id + a.position < b.section_id + b.position ? -1 : 1));
      return HttpResponse.json({ data, meta: { next_cursor: null } });
    }),
    http.post(`*${base}/api/v1/projects/:pid/tasks`, async ({ params, request }) => {
      await delay(latency);
      const b = (await request.json()) as { title: string; section_id: string; after_id?: string | null };
      const t = make(String(params.pid), b.section_id, b.title, '');
      tasks.push(t);
      place(t, b.after_id);
      return HttpResponse.json({ data: t, meta }, { status: 201 });
    }),
    http.post(`*${base}/api/v1/projects/:pid/tasks/batch`, async ({ params, request }) => {
      const b = (await request.json()) as { titles: string[]; section_id: string; after_id?: string | null };
      let after = b.after_id ?? null;
      const created = b.titles.map((title) => {
        const t = make(String(params.pid), b.section_id, title, '');
        tasks.push(t);
        place(t, after);
        after = t.id;
        return t;
      });
      return HttpResponse.json(
        { data: { data: created, meta: {} }, meta: { ...meta, batch_id: 'batch-1' } },
        { status: 201 },
      );
    }),
    http.patch(`*${base}/api/v1/tasks/:id`, async ({ params, request }) => {
      const t = tasks.find((x) => x.id === params.id)!;
      Object.assign(t, await request.json());
      t.version += 1;
      return HttpResponse.json({ data: t, meta });
    }),
    http.post(`*${base}/api/v1/tasks/:id/complete`, ({ params }) => {
      const t = tasks.find((x) => x.id === params.id)!;
      t.completed_at = new Date().toISOString();
      return HttpResponse.json({ data: t, meta });
    }),
    http.post(`*${base}/api/v1/tasks/:id/uncomplete`, ({ params }) => {
      const t = tasks.find((x) => x.id === params.id)!;
      t.completed_at = null;
      return HttpResponse.json({ data: t, meta });
    }),
    http.post(`*${base}/api/v1/undo`, () => {
      // emulate undo of the last completion in tests
      const t = [...tasks].reverse().find((x) => x.completed_at);
      if (t) t.completed_at = null;
      return HttpResponse.json({ undone: [] });
    }),
    http.delete(`*${base}/api/v1/tasks/:id`, ({ params }) => {
      tasks.splice(
        tasks.findIndex((x) => x.id === params.id),
        1,
      );
      return HttpResponse.json({ data: { ok: true }, meta });
    }),
  ];
}
