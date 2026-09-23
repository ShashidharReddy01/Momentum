import { http, HttpResponse } from 'msw';
import { ravi } from './fixtures';

const ana = {
  ...ravi,
  id: '01a0ccaf-8f68-77d2-a888-584ea1e80eb1',
  email: 'ana@acme-demo.test',
  name: 'Ana Souza',
};
const people = [ravi, ana];

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
export function projectHandlers(base = '', teamName = (id: string) => `Team ${id}`, seed: Partial<P>[] = []) {
  const projects: P[] = seed.map((x, i) => ({
    id: `seed-${i + 1}`,
    team_id: 'team-x',
    team_name: 'Product',
    name: `Seed ${i + 1}`,
    color: null,
    privacy: 'team',
    default_view: 'list',
    status: null,
    archived_at: null,
    owner_id: ravi.id,
    my_role: 'admin',
    is_favorite: false,
    version: 1,
    ...x,
  }));
  const members = new Map<string, { user: typeof ravi; role: string }[]>();
  const membersOf = (id: string) => {
    if (!members.has(id)) members.set(id, [{ user: ravi, role: 'admin' }]);
    return members.get(id)!;
  };
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000b001', batch_id: null, version: 1 };
  const detail = (p: P) => ({
    ...p,
    members: membersOf(p.id),
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
    http.post(`*${base}/api/v1/projects/:id/members`, async ({ params, request }) => {
      const b = (await request.json()) as { user_id: string; role: string };
      membersOf(String(params.id)).push({ user: people.find((u) => u.id === b.user_id)!, role: b.role });
      return HttpResponse.json({ data: { ok: true }, meta }, { status: 201 });
    }),
    http.patch(`*${base}/api/v1/projects/:id/members/:uid`, async ({ params, request }) => {
      const m = membersOf(String(params.id)).find((x) => x.user.id === params.uid)!;
      m.role = ((await request.json()) as { role: string }).role;
      return HttpResponse.json({ data: { ok: true }, meta });
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
