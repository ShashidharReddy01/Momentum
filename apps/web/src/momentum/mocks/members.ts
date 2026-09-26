import { http, HttpResponse } from 'msw';
import { ravi } from './fixtures';

type Member = {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  role: string;
  status: string;
  is_agent: boolean;
  timezone: string;
};

/** In-memory S2.7.3 members/invite API (`GET /users/members`, `POST /users/invite`). */
export function membersHandlers(base = '', initial: Member[] = [ravi]) {
  const members: Member[] = [...initial];
  return [
    http.get(`*${base}/api/v1/users/members`, () => HttpResponse.json({ data: members })),
    http.post(`*${base}/api/v1/users/invite`, async ({ request }) => {
      const body = (await request.json()) as { email: string; name?: string; role?: string };
      const email = body.email.trim().toLowerCase();
      const existing = members.find((m) => m.email === email);
      if (existing) return HttpResponse.json(existing);
      const invited: Member = {
        id: `invited-${members.length}`,
        email,
        name: body.name || email.split('@')[0] || email,
        avatar_url: null,
        role: body.role ?? 'member',
        status: 'invited',
        is_agent: false,
        timezone: 'UTC',
      };
      members.push(invited);
      return HttpResponse.json(invited);
    }),
  ];
}
