import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type Job = components['schemas']['JobOut'];
export type AuditEntry = components['schemas']['AuditEntry'];
export type JobStatus = 'failed' | 'todo' | 'doing' | 'succeeded' | 'cancelled' | 'aborting' | 'aborted';

export function useJobs(status: JobStatus) {
  const api = useApi();
  return useQuery({
    queryKey: ['admin', 'jobs', status],
    queryFn: async () => (await api.GET('/api/v1/admin/jobs', { params: { query: { status } } })).data!,
    refetchInterval: 15_000,
  });
}

export function useRetryJob() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.POST('/api/v1/admin/jobs/{job_id}/retry', { params: { path: { job_id: id } } })).data!,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'jobs'] }),
    onError: (e) => toastError(e, "Couldn't retry that job"),
  });
}

export interface AuditFilters {
  actor_id?: string;
  entity_type?: string;
  verb?: string;
  since?: string;
  until?: string;
}

/** The audit trail, newest first, 50 at a time ("Older" loads the next page). */
export function useAudit(filters: AuditFilters) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: ['admin', 'activity', filters],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      (
        await api.GET('/api/v1/admin/activity', {
          params: { query: { ...filters, limit: 50, ...(pageParam ? { before: pageParam } : {}) } },
        })
      ).data!.data,
    getNextPageParam: (last) => (last.length === 50 ? last[last.length - 1]!.created_at : undefined),
  });
}
