import { http, HttpResponse } from 'msw';
import type { RuntimeConfig } from '@/lib/config';
import { configFixture, ravi, workspace } from './fixtures';

const problem401 = (base: string) =>
  HttpResponse.json(
    {
      code: 'unauthenticated',
      title: 'Authentication required',
      status: 401,
      login_url: `${base}/dev/login`,
    },
    { status: 401, headers: { 'content-type': 'application/problem+json' } },
  );

/** Stateful handler set emulating the dev-auth backend. `me` overrides the fixture user (e.g.
 * `{ role: 'admin' }`) — S2.7.3's Members page gates its Invite button on workspace `role`. */
export function authHandlers(
  opts: {
    base?: string;
    loggedIn?: boolean;
    config?: Partial<RuntimeConfig>;
    me?: Partial<typeof ravi>;
  } = {},
) {
  const base = opts.base ?? '';
  let loggedIn = opts.loggedIn ?? false;
  const me = { ...ravi, ...opts.me };
  const requests: string[] = [];
  const handlers = [
    http.get(`*${base}/api/v1/config`, ({ request }) => {
      requests.push(new URL(request.url).pathname);
      return HttpResponse.json(configFixture({ base_path: base, ...opts.config }));
    }),
    http.get(`*${base}/api/v1/me`, ({ request }) => {
      requests.push(new URL(request.url).pathname);
      return loggedIn ? HttpResponse.json({ user: me, workspace }) : problem401(base);
    }),
    http.get(`*${base}/api/v1/dev/users`, () => HttpResponse.json([ravi])),
    http.post(`*${base}/api/v1/dev/login`, ({ request }) => {
      if (request.headers.get('x-requested-with') !== 'momentum') {
        return HttpResponse.json({ code: 'csrf_failed', status: 403 }, { status: 403 });
      }
      loggedIn = true;
      return HttpResponse.json(ravi);
    }),
    http.post(`*${base}/api/v1/auth/logout`, () => {
      loggedIn = false;
      return HttpResponse.json({ redirect_url: `${base}/dev/login` });
    }),
  ];
  return { handlers, requests };
}
