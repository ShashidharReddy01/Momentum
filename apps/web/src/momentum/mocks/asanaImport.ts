import { http, HttpResponse } from 'msw';

/** In-memory S7.4.2 Asana import API: discovery of a fixed workspace, and jobs that finish after
 * two steps with fixed counts. The importer itself is covered by `test_asana_import.py`; this
 * checks the wizard drives it (token per step, never stored) and shows the report. `steps` records
 * every step call's body so a test can see the token was sent each time. */
export function asanaImportHandlers(base = '') {
  const steps: { pat: string }[] = [];
  const jobs = new Map<string, Record<string, unknown>>();
  const job = (id: string, dryRun: boolean, left: number) => ({
    id,
    source: 'asana',
    status: left ? 'running' : 'done',
    dry_run: dryRun,
    remaining: left,
    stats: left
      ? { projects: 1, tasks: 2 }
      : {
          projects: 2,
          tasks: 5,
          subtasks: 1,
          users_invited: 1,
          ...(dryRun ? {} : { comments: 3 }),
          skipped: 1,
          skipped_items: ['task t3: a legacy section row, not a task'],
          unmapped: { 'formula fields imported as a text snapshot': 1 },
        },
    created_at: new Date().toISOString(),
    finished_at: left ? null : new Date().toISOString(),
  });
  const handlers = [
    http.post(`*${base}/api/v1/integrations/asana/discover`, async ({ request }) => {
      const b = (await request.json()) as { workspace_gid?: string; team_gid?: string };
      return HttpResponse.json({
        workspaces: [{ gid: 'ws1', name: 'Acme', archived: false }],
        teams: b.workspace_gid ? [{ gid: 'team1', name: 'Product', archived: false }] : [],
        projects: b.team_gid
          ? [
              { gid: 'p1', name: 'Website', archived: false },
              { gid: 'p2', name: 'Old site', archived: true },
            ]
          : [],
      });
    }),
    http.get(`*${base}/api/v1/integrations/asana/imports`, () =>
      HttpResponse.json({ data: [...jobs.values()], meta: { next_cursor: null } }),
    ),
    http.post(`*${base}/api/v1/integrations/asana/imports`, async ({ request }) => {
      const b = (await request.json()) as { dry_run: boolean };
      const id = `job-${jobs.size + 1}`;
      const j = { ...job(id, b.dry_run, 2), status: 'pending' };
      jobs.set(id, j);
      return HttpResponse.json(j, { status: 201 });
    }),
    http.post(`*${base}/api/v1/integrations/asana/imports/:id/step`, async ({ request, params }) => {
      steps.push((await request.json()) as { pat: string });
      const prev = jobs.get(String(params.id))!;
      const j = job(String(params.id), Boolean(prev.dry_run), Number(prev.remaining) - 1);
      jobs.set(j.id, j);
      return HttpResponse.json(j);
    }),
  ];
  return Object.assign(handlers, { steps });
}
