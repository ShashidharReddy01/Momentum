import { http, HttpResponse } from 'msw';

/** In-memory S2.7.1 Asana import API: always "succeeds" with a fixed stats payload, so the
 * frontend test can assert the result renders without needing a real (or fake-recorded) Asana
 * backend — the importer's own logic is covered by `test_asana_import.py`. */
export function asanaImportHandlers(base = '') {
  return [
    http.post(`*${base}/api/v1/integrations/asana/import`, () =>
      HttpResponse.json({
        id: 'job-1',
        source: 'asana',
        status: 'done',
        stats: { teams: 1, projects: 2, tasks: 5 },
        log: null,
        created_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
      }),
    ),
  ];
}
