import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type AsanaImportIn = components['schemas']['AsanaImportIn'];
export type ImportJob = components['schemas']['ImportJobOut'];

/** S2.7.1: runs synchronously — the request doesn't resolve until the whole import (or a
 * failure) does. See `integrations/asana_import/service.py`'s own docstring for why this isn't
 * a polled background job (the PAT is never persisted anywhere, queue included). */
export function useAsanaImport() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: AsanaImportIn) =>
      (await api.POST('/api/v1/integrations/asana/import', { body })).data!,
    // a successful import can create a new team and projects — invalidate by query-key prefix
    // rather than importing `teamKeys`/`projectKeys` from those features (no new cross-feature
    // coupling for a one-off invalidation). A real gap found while writing J6's e2e journey:
    // without this, the sidebar never showed the imported team until a manual reload.
    onSuccess: (job) => {
      if (job.status === 'done') {
        void qc.invalidateQueries({
          predicate: (q) => q.queryKey[0] === 'teams' || q.queryKey[0] === 'projects',
        });
      }
    },
    onError: (e) => toastError(e, "Couldn't import from Asana"),
  });
}
