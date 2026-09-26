import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type StatusUpdate = components['schemas']['StatusUpdateOut'];
export type StatusUpdateIn = components['schemas']['StatusUpdateIn'];
export type StatusDraft = components['schemas']['StatusDraftOut'];
export type Status = StatusUpdateIn['status'];

export const statusKeys = {
  list: (projectId: string) => ['status-updates', projectId] as const,
};

/** A project's status updates, newest first (S3.4.3). */
export function useStatusUpdates(projectId: string) {
  const api = useApi();
  return useQuery({
    queryKey: statusKeys.list(projectId),
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/status-updates', {
          params: { path: { project_id: projectId } },
        })
      ).data!.data,
  });
}

/** Post an update (sets the project's status). The response carries the undo handle. */
export function usePostStatus(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: StatusUpdateIn) =>
      (
        await api.POST('/api/v1/projects/{project_id}/status-updates', {
          params: { path: { project_id: projectId } },
          body,
        })
      ).data!,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: statusKeys.list(projectId) });
      void qc.invalidateQueries({ queryKey: ['projects'] });
    },
    onError: (e) => toastError(e, "Couldn't post the update"),
  });
}

/** Mo's draft from the project's recent activity (stores nothing). */
export function useStatusDraft(projectId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async () =>
      (
        await api.POST('/api/v1/ai/projects/{project_id}/status-draft', {
          params: { path: { project_id: projectId } },
          body: { days: 7 },
        })
      ).data!,
  });
}
