import { http, HttpResponse } from 'msw';
import { ravi } from './fixtures';

const ana = {
  ...ravi,
  id: '01a0ccaf-8f68-77d2-a888-584ea1e80eb1',
  email: 'ana@acme-demo.test',
  name: 'Ana Souza',
};

/** In-memory teams API (synthetic data) for component and flow tests. */
export function teamHandlers(base = '') {
  type Member = { user: typeof ravi; role: string };
  type T = {
    id: string;
    name: string;
    description: string | null;
    color: string | null;
    version: number;
    members: Member[];
  };
  const teams: T[] = [];
  const out = (t: T) => ({
    id: t.id,
    name: t.name,
    description: t.description,
    color: t.color,
    version: t.version,
    my_role: t.members.find((m) => m.user.id === ravi.id)?.role ?? null,
    member_count: t.members.length,
  });
  const meta = { activity_id: '01a0ccaf-0000-7000-8000-00000000a001', batch_id: null, version: 1 };
  return [
    http.get(`*${base}/api/v1/users`, () =>
      HttpResponse.json({ data: [ravi, ana], meta: { next_cursor: null } }),
    ),
    http.get(`*${base}/api/v1/teams`, () =>
      HttpResponse.json({ data: teams.map(out), meta: { next_cursor: null } }),
    ),
    http.post(`*${base}/api/v1/teams`, async ({ request }) => {
      const body = (await request.json()) as {
        name: string;
        description?: string | null;
        color?: string | null;
      };
      const t: T = {
        id: `team-${teams.length + 1}`,
        name: body.name,
        description: body.description ?? null,
        color: body.color ?? null,
        version: 1,
        members: [{ user: ravi, role: 'lead' }],
      };
      teams.push(t);
      return HttpResponse.json({ data: { ...out(t), members: t.members }, meta }, { status: 201 });
    }),
    http.get(`*${base}/api/v1/teams/:id`, ({ params }) => {
      const t = teams.find((x) => x.id === params.id);
      return t
        ? HttpResponse.json({ ...out(t), members: t.members })
        : HttpResponse.json({ code: 'not_found', status: 404 }, { status: 404 });
    }),
    http.patch(`*${base}/api/v1/teams/:id`, async ({ params, request }) => {
      const t = teams.find((x) => x.id === params.id)!;
      Object.assign(t, (await request.json()) as Partial<T>);
      t.version += 1;
      return HttpResponse.json({ data: out(t), meta });
    }),
    http.post(`*${base}/api/v1/teams/:id/members`, async ({ params, request }) => {
      const t = teams.find((x) => x.id === params.id)!;
      const { user_id } = (await request.json()) as { user_id: string };
      t.members.push({ user: user_id === ana.id ? ana : ravi, role: 'member' });
      return HttpResponse.json({ data: { ok: true }, meta }, { status: 201 });
    }),
  ];
}
