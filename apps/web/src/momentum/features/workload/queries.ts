import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type Workload = components['schemas']['WorkloadOut'];
export type PersonLoad = components['schemas']['PersonLoadOut'];
export type WeekLoad = components['schemas']['WeekLoadOut'];
export type WorkloadTask = components['schemas']['WorkloadTaskOut'];

export const workloadKeys = {
  all: ['workload'] as const,
  view: (start: string, weeks: number, projectId: string | null) =>
    ['workload', start, weeks, projectId ?? 'all'] as const,
};

export function useWorkload(start: string, weeks: number, projectId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: workloadKeys.view(start, weeks, projectId),
    queryFn: async () =>
      (
        await api.GET('/api/v1/workload', {
          params: { query: { start, weeks, ...(projectId ? { project_id: projectId } : {}) } },
        })
      ).data!,
    placeholderData: (prev) => prev, // paging weeks keeps the grid on screen
  });
}

/** Capacity edits: a person's usual hours, one week's hours (time off), the workspace default. */
export function useCapacityMutations() {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const refresh = () => qc.invalidateQueries({ queryKey: workloadKeys.all });
  const done = (message: string) => (res: { meta: components['schemas']['MutationMeta'] }) => {
    void refresh();
    undoToast(message, res.meta, () => void refresh());
  };

  const hours = useMutation({
    mutationFn: async (v: { userId: string; hours: number | null; message: string }) =>
      (
        await api.PUT('/api/v1/workload/people/{user_id}/hours', {
          params: { path: { user_id: v.userId } },
          body: { hours: v.hours },
        })
      ).data!,
    onSuccess: (res, v) => done(v.message)(res),
    onError: (e) => toastError(e, "Couldn't change the hours"),
  });
  const week = useMutation({
    mutationFn: async (v: { userId: string; week: string; hours: number | null; message: string }) =>
      (
        await api.PUT('/api/v1/workload/people/{user_id}/weeks/{week_start}', {
          params: { path: { user_id: v.userId, week_start: v.week } },
          body: { hours: v.hours },
        })
      ).data!,
    onSuccess: (res, v) => done(v.message)(res),
    onError: (e) => toastError(e, "Couldn't change that week"),
  });
  const workspace = useMutation({
    mutationFn: async (v: { hours: number | null; message: string }) =>
      (await api.PUT('/api/v1/workload/settings', { body: { hours: v.hours } })).data!,
    onSuccess: (res, v) => done(v.message)(res),
    onError: (e) => toastError(e, "Couldn't change the default hours"),
  });
  return { hours, week, workspace };
}

/**
 * Dragging a task in the grid, always one undoable step: to another week (same person) moves its
 * dates by whole weeks through the dependency-aware reschedule, so work waiting on it moves too;
 * to another person reassigns it (and, if also another week, moves its own dates in the same edit).
 */
export function useMoveTask() {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const refresh = () => qc.invalidateQueries({ queryKey: workloadKeys.all });
  return useMutation({
    mutationFn: async (v: {
      task: WorkloadTask;
      assigneeId?: string | null;
      dates?: { start_on: string | null; due_on: string };
      message: string;
    }) => {
      const meta =
        v.assigneeId === undefined && v.dates
          ? (
              await api.POST('/api/v1/tasks/{task_id}/reschedule', {
                params: { path: { task_id: v.task.id } },
                body: { ...v.dates, cascade: true },
              })
            ).data!.meta
          : (
              await api.PATCH('/api/v1/tasks/{task_id}', {
                params: { path: { task_id: v.task.id } },
                body: { ...(v.assigneeId !== undefined ? { assignee_id: v.assigneeId } : {}), ...v.dates },
              })
            ).data!.meta;
      await refresh(); // settle once the grid shows the move (no snap back)
      return meta;
    },
    onSuccess: (meta, v) => undoToast(v.message, meta, () => void refresh()),
    onError: (e) => {
      toastError(e, "Couldn't move the task");
      void refresh();
    },
  });
}
