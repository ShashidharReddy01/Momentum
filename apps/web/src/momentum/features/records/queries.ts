import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

/** Phase 7.6 S76-08: records (the review screen, the Records tab, the task's record panel),
 * entities and their activity. */

export type RecordRow = components['schemas']['RecordOut'];
export type RecordDetail = components['schemas']['RecordDetailOut'];
export type RecordType = components['schemas']['RecordTypeOut'];
export type RecordSource = components['schemas']['RecordSourceOut'];
export type RecordOp = components['schemas']['RecordPatchIn']['ops'][number];
export type QueryResult = components['schemas']['QueryResult'];
export type Entity = components['schemas']['EntityOut'];
export type EntityActivity = components['schemas']['EntityActivityOut'];

export interface RecordFilters {
  type?: string;
  status?: string[];
  entity_id?: string;
  q?: string;
  from?: string;
  to?: string;
}

export const recordKeys = {
  all: ['records'] as const,
  types: (projectId: string | null) => ['records', 'types', projectId] as const,
  list: (projectId: string | null, f: RecordFilters & { task_id?: string }) =>
    ['records', 'list', projectId, f] as const,
  detail: (id: string) => ['records', id] as const,
  source: (id: string) => ['records', id, 'source'] as const,
  totals: (projectId: string, f: RecordFilters) => ['records', 'totals', projectId, f] as const,
  entities: (q: string, type: string | null, status: string) =>
    ['entities', 'list', q, type, status] as const,
  entity: (id: string) => ['entities', id] as const,
  entityActivity: (id: string) => ['entities', id, 'activity'] as const,
};

export function useRecordTypes(projectId: string | null, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: recordKeys.types(projectId),
    enabled,
    queryFn: async () =>
      (await api.GET('/api/v1/records/types', { params: { query: { project_id: projectId ?? undefined } } }))
        .data!.data,
  });
}

export function useRecords(
  projectId: string | null,
  f: RecordFilters & { task_id?: string },
  enabled = true,
) {
  const api = useApi();
  return useQuery({
    queryKey: recordKeys.list(projectId, f),
    enabled,
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (
        await api.GET('/api/v1/records', {
          params: {
            query: {
              project_id: projectId ?? undefined,
              task_id: f.task_id,
              type: f.type || undefined,
              status: f.status?.length ? f.status : undefined,
              entity_id: f.entity_id || undefined,
              q: f.q || undefined,
              from: f.from || undefined,
              to: f.to || undefined,
              limit: 200,
            },
          },
        })
      ).data!.data,
  });
}

/** Totals per currency, from the server (never added up here). */
export function useRecordTotals(projectId: string, f: RecordFilters, enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: recordKeys.totals(projectId, f),
    enabled: enabled && !!f.type,
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (
        await api.POST('/api/v1/records/query', {
          body: {
            type: f.type!,
            project_ids: [projectId],
            status: f.status ?? [],
            entity_id: f.entity_id || null,
            date_from: f.from || null,
            date_to: f.to || null,
            measures: [{ op: 'count' }, { op: 'sum', path: 'amount' }],
            filters: [],
            group_by: [],
            order: 'value_desc',
            limit: 50,
          },
        })
      ).data!,
  });
}

export function useRecord(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: recordKeys.detail(id),
    queryFn: async () =>
      (await api.GET('/api/v1/records/{record_id}', { params: { path: { record_id: id } } })).data!,
  });
}

export function useRecordSource(id: string, enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: recordKeys.source(id),
    enabled,
    retry: false,
    staleTime: Infinity,
    queryFn: async () =>
      (await api.GET('/api/v1/records/{record_id}/source', { params: { path: { record_id: id } } })).data!,
  });
}

/** Save correction operations; a stale version comes back as a 409 for the caller to handle. */
export function usePatchRecord(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { ops: RecordOp[]; expected_version: number; reason?: string | null }) =>
      (
        await api.PATCH('/api/v1/records/{record_id}', {
          params: { path: { record_id: id } },
          body,
        })
      ).data!,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: recordKeys.detail(id) });
      void qc.invalidateQueries({ queryKey: ['records', 'list'] });
      void qc.invalidateQueries({ queryKey: ['records', 'totals'] });
    },
  });
}

export function useBulkStatus() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { ids: string[]; status: 'needs_review' | 'void'; reason?: string }) =>
      (await api.POST('/api/v1/records/status', { body })).data!,
    onSuccess: () => void qc.invalidateQueries({ queryKey: recordKeys.all }),
    onError: (e) => toastError(e, "Couldn't change the records"),
  });
}

export function useEntities(q: string, type: string | null, status = 'active') {
  const api = useApi();
  return useQuery({
    queryKey: recordKeys.entities(q, type, status),
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (
        await api.GET('/api/v1/entities', {
          params: { query: { q: q || undefined, type: type ?? undefined, status, limit: 200 } },
        })
      ).data!.data,
  });
}

export function useEntity(id: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: recordKeys.entity(id ?? ''),
    enabled: !!id,
    queryFn: async () =>
      (await api.GET('/api/v1/entities/{entity_id}', { params: { path: { entity_id: id! } } })).data!,
  });
}

export function useEntityActivity(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: recordKeys.entityActivity(id),
    queryFn: async () =>
      (await api.GET('/api/v1/entities/{entity_id}/activity', { params: { path: { entity_id: id } } })).data!
        .data,
  });
}

export function useEntityActions(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  const done = () => void qc.invalidateQueries({ queryKey: ['entities'] });
  return {
    merge: useMutation({
      mutationFn: async (intoId: string) =>
        (
          await api.POST('/api/v1/entities/{entity_id}/merge', {
            params: { path: { entity_id: id } },
            body: { into_id: intoId },
          })
        ).data!,
      onSuccess: done,
      onError: (e) => toastError(e, "Couldn't merge"),
    }),
    archive: useMutation({
      mutationFn: async () =>
        (await api.POST('/api/v1/entities/{entity_id}/archive', { params: { path: { entity_id: id } } }))
          .data!,
      onSuccess: done,
      onError: (e) => toastError(e, "Couldn't archive"),
    }),
    alias: useMutation({
      mutationFn: async (alias: string) =>
        (
          await api.POST('/api/v1/entities/{entity_id}/aliases', {
            params: { path: { entity_id: id } },
            body: { alias },
          })
        ).data!,
      onSuccess: done,
      onError: (e) => toastError(e, "Couldn't add the alias"),
    }),
  };
}
