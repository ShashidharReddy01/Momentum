import { http, HttpResponse } from 'msw';
import { ravi } from './fixtures';

type P = {
  id: string;
  team_id: string;
  team_name: string;
  name: string;
  color: string | null;
  privacy: string;
  default_view: string;
  status: null;
  archived_at: string | null;
  owner_id: string;
  my_role: string;
  is_favorite: boolean;
  version: number;
};

/** In-memory projects + favorites API (synthetic data) for flow tests. */
export function projectHandlers(base = '', teamName = (id: string) => `Team ${id}`) {
  const projects: P[] = [];
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000b001', batch_id: null, version: 1 };
  const detail = (p: P) => ({
    ...p,
    members: [{ user: ravi, role: 'admin' }],
    sections: [{ id: `${p.id}-s1`, name: 'To do', position: 'V' }],
  });
  const find = (id: unknown) => projects.find((p) => p.id === id);
  return [
    http.get(`*${base}/api/v1/projects`, ({ request }) => {
      const url = new URL(request.url);
      const team = url.searchParams.get('team_id');
      const archived = url.searchParams.get('archived') === 'true';
      const data = projects.filter((p) => (!team || p.team_id === team) && !!p.archived_at === archived);
      return HttpResponse.json({ data, meta: { next_cursor: null } });
    }),
    http.post(`*${base}/api/v1/projects`, async ({ request }) => {
      const b = (await request.json()) as { team_id: string; name: string; privacy?: string; color?: string };
      const p: P = {
        id: `project-${projects.length + 1}`,
        team_id: b.team_id,
        team_name: teamName(b.team_id),
        name: b.name,
        color: b.color ?? null,
        privacy: b.privacy ?? 'team',
        default_view: 'list',
        status: null,
        archived_at: null,
        owner_id: ravi.id,
        my_role: 'admin',
        is_favorite: false,
        version: 1,
      };
      projects.push(p);
      return HttpResponse.json({ data: detail(p), meta }, { status: 201 });
    }),
    http.get(`*${base}/api/v1/projects/:id`, ({ params }) => {
      const p = find(params.id);
      return p
        ? HttpResponse.json(detail(p))
        : HttpResponse.json({ code: 'not_found', status: 404 }, { status: 404 });
    }),
    http.patch(`*${base}/api/v1/projects/:id`, async ({ params, request }) => {
      const p = find(params.id)!;
      Object.assign(p, await request.json());
      return HttpResponse.json({ data: p, meta });
    }),
    http.post(`*${base}/api/v1/projects/:id/archive`, ({ params }) => {
      const p = find(params.id)!;
      p.archived_at = '2026-09-23T10:00:00Z';
      return HttpResponse.json({ data: p, meta });
    }),
    http.post(`*${base}/api/v1/projects/:id/unarchive`, ({ params }) => {
      const p = find(params.id)!;
      p.archived_at = null;
      return HttpResponse.json({ data: p, meta });
    }),
    http.get(`*${base}/api/v1/favorites`, () =>
      HttpResponse.json({
        data: projects.filter((p) => p.is_favorite && !p.archived_at),
        meta: { next_cursor: null },
      }),
    ),
    http.put(`*${base}/api/v1/favorites/projects/:id`, ({ params }) => {
      find(params.id)!.is_favorite = true;
      return HttpResponse.json({ ok: true });
    }),
    http.delete(`*${base}/api/v1/favorites/projects/:id`, ({ params }) => {
      find(params.id)!.is_favorite = false;
      return HttpResponse.json({ ok: true });
    }),
  ];
}
