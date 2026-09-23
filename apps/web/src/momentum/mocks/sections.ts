import { http, HttpResponse } from 'msw';

type S = { id: string; project_id: string; name: string; position: string; version: number };

/** In-memory sections API. Positions are simple zero-padded numbers (enough for tests). */
export function sectionHandlers(base = '', initial: Record<string, string[]> = {}) {
  const sections: S[] = [];
  let n = 0;
  const pos = (i: number) => String(1000 + i * 10).padStart(6, '0');
  for (const [pid, names] of Object.entries(initial)) {
    names.forEach((name, i) =>
      sections.push({ id: `sec-${++n}`, project_id: pid, name, position: pos(i), version: 1 }),
    );
  }
  const of = (pid: string) =>
    sections.filter((s) => s.project_id === pid).sort((a, b) => (a.position < b.position ? -1 : 1));
  const renumber = (ordered: S[]) => ordered.forEach((s, i) => (s.position = pos(i)));
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000c001', batch_id: null, version: 1 };
  const place = (pid: string, item: S, afterId?: string | null, beforeId?: string | null) => {
    const rest = of(pid).filter((s) => s.id !== item.id);
    let i = rest.length;
    if (afterId) i = rest.findIndex((s) => s.id === afterId) + 1;
    else if (beforeId) i = rest.findIndex((s) => s.id === beforeId);
    renumber([...rest.slice(0, i), item, ...rest.slice(i)]);
  };
  return [
    http.get(`*${base}/api/v1/projects/:pid/sections`, ({ params }) =>
      HttpResponse.json({ data: of(String(params.pid)), meta: { next_cursor: null } }),
    ),
    http.post(`*${base}/api/v1/projects/:pid/sections`, async ({ params, request }) => {
      const b = (await request.json()) as { name: string; after_id?: string; before_id?: string };
      const s: S = {
        id: `sec-${++n}`,
        project_id: String(params.pid),
        name: b.name,
        position: '',
        version: 1,
      };
      sections.push(s);
      place(s.project_id, s, b.after_id, b.before_id);
      return HttpResponse.json({ data: s, meta }, { status: 201 });
    }),
    http.patch(`*${base}/api/v1/sections/:id`, async ({ params, request }) => {
      const s = sections.find((x) => x.id === params.id)!;
      s.name = ((await request.json()) as { name: string }).name;
      return HttpResponse.json({ data: s, meta });
    }),
    http.post(`*${base}/api/v1/sections/:id/move`, async ({ params, request }) => {
      const s = sections.find((x) => x.id === params.id)!;
      const b = (await request.json()) as { after_id?: string | null; before_id?: string | null };
      place(s.project_id, s, b.after_id, b.before_id);
      return HttpResponse.json({ data: s, meta });
    }),
    http.delete(`*${base}/api/v1/sections/:id`, ({ params }) => {
      const i = sections.findIndex((x) => x.id === params.id);
      sections.splice(i, 1);
      return HttpResponse.json({ data: { ok: true }, meta: { ...meta, batch_id: 'b1' } });
    }),
  ];
}
