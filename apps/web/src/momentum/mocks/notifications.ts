import { http, HttpResponse } from 'msw';

type N = {
  id: string;
  kind: string;
  entity_type: string;
  entity_id: string;
  activity_id: string | null;
  title: string;
  snippet: string | null;
  read_at: string | null;
  archived_at: string | null;
  created_at: string;
};

const DEFAULT_PREFS = {
  assigned: 'in_app' as const,
  mentioned: 'in_app' as const,
  commented: 'in_app' as const,
  completed: 'in_app' as const,
  due_soon: 'in_app' as const,
  overdue: 'in_app' as const,
  digest_time: null as string | null,
};

/** In-memory S2.5 notifications API. Seeded with `initial` rows (most-recent-first is the
 * caller's job when seeding). */
export function notificationHandlers(base = '', initial: N[] = []) {
  const rows: N[] = [...initial];
  let prefs = { ...DEFAULT_PREFS };

  return [
    http.get(`*${base}/api/v1/notifications`, ({ request }) => {
      const url = new URL(request.url);
      const archived = url.searchParams.get('archived') === 'true';
      const data = rows.filter((n) => (archived ? !!n.archived_at : !n.archived_at));
      return HttpResponse.json({ data, meta: { next_cursor: null } });
    }),
    http.get(`*${base}/api/v1/notifications/unread-count`, () => {
      const count = rows.filter((n) => !n.archived_at && !n.read_at).length;
      return HttpResponse.json({ count });
    }),
    http.post(`*${base}/api/v1/notifications/:id/read`, ({ params }) => {
      const n = rows.find((x) => x.id === params.id)!;
      n.read_at = new Date().toISOString();
      return HttpResponse.json(n);
    }),
    http.post(`*${base}/api/v1/notifications/:id/unread`, ({ params }) => {
      const n = rows.find((x) => x.id === params.id)!;
      n.read_at = null;
      return HttpResponse.json(n);
    }),
    http.post(`*${base}/api/v1/notifications/:id/archive`, ({ params }) => {
      const n = rows.find((x) => x.id === params.id)!;
      n.archived_at = new Date().toISOString();
      return HttpResponse.json(n);
    }),
    http.post(`*${base}/api/v1/notifications/:id/unarchive`, ({ params }) => {
      const n = rows.find((x) => x.id === params.id)!;
      n.archived_at = null;
      return HttpResponse.json(n);
    }),
    http.get(`*${base}/api/v1/me/prefs/notifications`, () => HttpResponse.json(prefs)),
    http.put(`*${base}/api/v1/me/prefs/notifications`, async ({ request }) => {
      prefs = (await request.json()) as typeof prefs;
      return HttpResponse.json(prefs);
    }),
  ];
}
