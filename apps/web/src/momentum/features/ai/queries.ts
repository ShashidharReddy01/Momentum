import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type AiAction = components['schemas']['AiActionOut'];
export type AiOperation = components['schemas']['AiOperationOut'];
export type DiffRow = components['schemas']['DiffRowOut'];
export type ApplyOutcome = components['schemas']['ApplyOut']['outcome'];

export const aiKeys = {
  action: (id: string) => ['ai', 'actions', id] as const,
};

/** One proposed AI action (S3.1.3). */
export function useAiAction(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: aiKeys.action(id),
    queryFn: async () =>
      (await api.GET('/api/v1/ai/actions/{action_id}', { params: { path: { action_id: id } } })).data!.data,
  });
}

/** Apply / dismiss / undo a proposed action. Every response carries the action's new state,
 * which replaces the cached one; applying or undoing also refreshes whatever it changed. */
export function useAiActionMutations(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  const path = { params: { path: { action_id: id } } };
  const put = (a: AiAction) => qc.setQueryData(aiKeys.action(id), a);

  const apply = useMutation({
    mutationFn: async (confirmHighRisk: boolean) =>
      (
        await api.POST('/api/v1/ai/actions/{action_id}/apply', {
          ...path,
          body: { confirm_high_risk: confirmHighRisk },
        })
      ).data!,
    onSuccess: (r) => {
      put(r.data);
      if (r.outcome === 'applied') void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'ai' });
    },
    onError: (e) => toastError(e, "Couldn't apply the changes"),
  });
  const reject = useMutation({
    mutationFn: async () => (await api.POST('/api/v1/ai/actions/{action_id}/reject', path)).data!.data,
    onSuccess: put,
    onError: (e) => toastError(e, "Couldn't dismiss the suggestion"),
  });
  const undo = useMutation({
    mutationFn: async () => (await api.POST('/api/v1/ai/actions/{action_id}/undo', path)).data!.data,
    onSuccess: (a) => {
      put(a);
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'ai' });
    },
    onError: (e) => toastError(e, "Couldn't undo"),
  });
  return { apply, reject, undo };
}
