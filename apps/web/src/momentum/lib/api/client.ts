import createClient, { type Middleware } from 'openapi-fetch';
import { toApiError } from './errors';
import type { paths } from './schema';

export type MomentumClient = ReturnType<typeof createClient<paths>>;

export const UNAUTHENTICATED_EVENT = 'momentum:unauthenticated';

/** Typed API client. Paths in `schema.d.ts` already include `/api/v1`, so the base URL is
 * the app's base path (origin-relative; works same-origin behind Easy Auth). */
export function createApiClient(basePath: string, origin = window.location.origin): MomentumClient {
  const client = createClient<paths>({
    baseUrl: new URL(basePath || '/', origin).toString().replace(/\/$/, ''),
    credentials: 'include',
  });
  const middleware: Middleware = {
    onRequest({ request }) {
      request.headers.set('X-Requested-With', 'momentum');
      return request;
    },
    async onResponse({ response }) {
      if (response.ok) return response;
      const body: unknown = await response
        .clone()
        .json()
        .catch(() => null);
      const err = toApiError(response.status, body);
      if (err.status === 401) window.dispatchEvent(new CustomEvent(UNAUTHENTICATED_EVENT, { detail: err }));
      throw err;
    },
  };
  client.use(middleware);
  return client;
}
