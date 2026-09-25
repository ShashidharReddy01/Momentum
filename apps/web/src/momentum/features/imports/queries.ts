import { useMutation } from '@tanstack/react-query';
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
  return useMutation({
    mutationFn: async (body: AsanaImportIn) =>
      (await api.POST('/api/v1/integrations/asana/import', { body })).data!,
    onError: (e) => toastError(e, "Couldn't import from Asana"),
  });
}
