import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef } from 'react';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type ImportJob = components['schemas']['ImportJobOut'];
export type AsanaJobIn = components['schemas']['AsanaJobIn'];
export type AsanaThing = components['schemas']['AsanaThing'];
export type AsanaDiscovery = components['schemas']['AsanaDiscoverOut'];

export const importKeys = { all: ['imports', 'asana'] as const };

/** Browse Asana with a token (never stored): workspaces, then a workspace's teams, then a team's
 * projects. A mutation, because the token travels in the body. */
export function useAsanaDiscover() {
  const api = useApi();
  return useMutation({
    mutationFn: async (v: { pat: string; workspace_gid?: string; team_gid?: string }) =>
      (await api.POST('/api/v1/integrations/asana/discover', { body: v })).data!,
    onError: (e) => toastError(e, "Couldn't reach Asana"),
  });
}

/** Recent imports (yours; every one for an admin). */
export function useImports() {
  const api = useApi();
  return useQuery({
    queryKey: importKeys.all,
    queryFn: async () => (await api.GET('/api/v1/integrations/asana/imports')).data!.data,
  });
}

/**
 * S7.4.2: an import runs as steps of up to ~40 s each: create the job (no token), then call its
 * step with the token until it's done. The token lives only in this page's memory. `run` drives
 * the loop and reports every step's job (counts so far, items left); `stop` ends it after the
 * current step (the job keeps its place: resume it from the list with the token again).
 */
export function useImportRunner() {
  const api = useApi();
  const qc = useQueryClient();
  const stopped = useRef(false); // survives re-renders while a run is in flight
  const refreshApp = () =>
    void qc.invalidateQueries({
      predicate: (q) => ['teams', 'projects', 'people', 'imports'].includes(String(q.queryKey[0])),
    });

  const create = async (body: AsanaJobIn) =>
    (await api.POST('/api/v1/integrations/asana/imports', { body })).data!;
  const step = async (jobId: string, pat: string) =>
    (
      await api.POST('/api/v1/integrations/asana/imports/{job_id}/step', {
        params: { path: { job_id: jobId } },
        body: { pat },
      })
    ).data!;

  const run = async (job: ImportJob, pat: string, onStep: (j: ImportJob) => void): Promise<ImportJob> => {
    stopped.current = false;
    let current = job;
    onStep(current);
    while (!stopped.current && current.status !== 'done' && current.status !== 'failed') {
      current = await step(current.id, pat);
      onStep(current);
    }
    if (current.status === 'done' && !current.dry_run) refreshApp();
    void qc.invalidateQueries({ queryKey: importKeys.all });
    return current;
  };
  return {
    create,
    run,
    stop: () => {
      stopped.current = true;
    },
  };
}
