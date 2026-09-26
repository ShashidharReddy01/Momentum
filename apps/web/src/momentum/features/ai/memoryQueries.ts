import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type MemoryBullet = components['schemas']['MemoryOut'];

export const memoryKeys = {
  workspace: ['ai', 'memory', 'workspace'] as const,
  prefs: ['ai', 'prefs'] as const,
};
export type AiPrefs = components['schemas']['AiPrefs'];

/** My AI preferences (S3.2.2). */
export function useAiPrefs() {
  const api = useApi();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: memoryKeys.prefs,
    queryFn: async () => (await api.GET('/api/v1/ai/prefs')).data!,
  });
  const save = useMutation({
    mutationFn: async (body: AiPrefs) => (await api.PUT('/api/v1/ai/prefs', { body })).data!,
    onSuccess: (p) => qc.setQueryData(memoryKeys.prefs, p),
    onError: (e) => toastError(e, "Couldn't save that setting"),
  });
  return { prefs: q.data, save };
}

/** Workspace memory bullets (S3.1.5). */
export function useWorkspaceMemory() {
  const api = useApi();
  return useQuery({
    queryKey: memoryKeys.workspace,
    queryFn: async () =>
      (await api.GET('/api/v1/ai/memory', { params: { query: { scope: 'workspace' } } })).data!.data,
  });
}

/** Add / edit / remove a bullet. Each change offers Undo. */
export function useMemoryMutations() {
  const api = useApi();
  const qc = useQueryClient();
  const notify = useUndoToast();
  const settle = () => void qc.invalidateQueries({ queryKey: memoryKeys.workspace });

  const create = useMutation({
    mutationFn: async (text: string) =>
      (await api.POST('/api/v1/ai/memory', { body: { scope: 'workspace', text } })).data!,
    onSuccess: (r) => notify('Memory added', r.meta),
    onError: (e) => toastError(e, "Couldn't add that"),
    onSettled: settle,
  });
  const update = useMutation({
    mutationFn: async (v: { id: string; text: string }) =>
      (
        await api.PATCH('/api/v1/ai/memory/{memory_id}', {
          params: { path: { memory_id: v.id } },
          body: { text: v.text },
        })
      ).data!,
    onSuccess: (r) => notify('Memory updated', r.meta),
    onError: (e) => toastError(e, "Couldn't save that"),
    onSettled: settle,
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      (await api.DELETE('/api/v1/ai/memory/{memory_id}', { params: { path: { memory_id: id } } })).data!,
    onSuccess: (r) => notify('Memory removed', r.meta),
    onError: (e) => toastError(e, "Couldn't remove that"),
    onSettled: settle,
  });
  return { create, update, remove };
}
