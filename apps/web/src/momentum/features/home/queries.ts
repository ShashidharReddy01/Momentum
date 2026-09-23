import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import { syncTask } from '@/features/tasks';

export type HomeData = components['schemas']['HomeOut'];
export type HomeTask = components['schemas']['MyTaskOut'];
export type HomeProject = components['schemas']['HomeProjectOut'];
export const homeKey = ['home'] as const;

export function useHome() {
  const api = useApi();
  return useQuery({
    queryKey: homeKey,
    queryFn: async () => (await api.GET('/api/v1/home')).data!,
  });
}

/** Complete a task from Home: it leaves the card at once, with undo. */
export function useCompleteFromHome() {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: homeKey });
    void qc.invalidateQueries({ queryKey: ['me', 'tasks'] });
  };
  return useMutation({
    mutationFn: async (id: string) =>
      (await api.POST('/api/v1/tasks/{task_id}/complete', { params: { path: { task_id: id } } })).data!,
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: homeKey });
      qc.setQueryData<HomeData>(homeKey, (old) =>
        old
          ? {
              ...old,
              priorities: old.priorities.map((t) =>
                t.id === id ? { ...t, completed_at: new Date().toISOString() } : t,
              ),
            }
          : old,
      );
    },
    onSuccess: (res, id) => {
      syncTask(qc, id, { completed_at: res.data.completed_at });
      undoToast('Task completed', res.meta, refresh);
      // let the check animation play before the list closes up
      setTimeout(refresh, 900);
    },
    onError: (e) => {
      toastError(e, "Couldn't complete the task");
      refresh();
    },
  });
}
