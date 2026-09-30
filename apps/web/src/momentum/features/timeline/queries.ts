import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type DependencyEdge = components['schemas']['DependencyEdgeOut'];
export type ReschedulePlan = components['schemas']['RescheduleOut'];
export type DatesPatch = { start_on?: string | null; due_on?: string | null };

export const timelineKeys = {
  dependencies: (projectId: string) => ['projects', projectId, 'dependencies'] as const,
};

/** Every dependency between two tasks of the project, in one round trip (S6.1.1a). */
export function useProjectDependencies(projectId: string) {
  const api = useApi();
  return useQuery({
    queryKey: timelineKeys.dependencies(projectId),
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/dependencies', {
          params: { path: { project_id: projectId } },
        })
      ).data!.data,
  });
}

/**
 * Dependency-aware rescheduling (S6.1.2): `preview` asks the server what moving a task would do to
 * the work that waits on it (nothing is written); `apply` moves the task and those dependents as
 * one undo batch.
 */
export function useReschedule(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const refresh = () => qc.invalidateQueries({ queryKey: ['projects', projectId, 'tasks'] });

  const preview = async (taskId: string, patch: DatesPatch): Promise<ReschedulePlan> =>
    (
      await api.POST('/api/v1/tasks/{task_id}/reschedule/preview', {
        params: { path: { task_id: taskId } },
        body: { ...patch, cascade: true },
      })
    ).data!;

  const apply = useMutation({
    mutationFn: async (v: { taskId: string; patch: DatesPatch; message: string }) => {
      const res = (
        await api.POST('/api/v1/tasks/{task_id}/reschedule', {
          params: { path: { task_id: v.taskId } },
          body: { ...v.patch, cascade: true },
        })
      ).data!;
      await refresh(); // settle only once the new dates are on screen (no snap back)
      return res;
    },
    onSuccess: (res, v) => undoToast(v.message, res.meta, () => void refresh()),
    onError: (e) => {
      toastError(e, "Couldn't reschedule");
      void refresh();
    },
  });

  return { preview, apply };
}
