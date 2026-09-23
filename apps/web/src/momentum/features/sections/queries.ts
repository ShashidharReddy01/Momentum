import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type Section = components['schemas']['SectionOut'];

export const sectionKeys = {
  byProject: (projectId: string) => ['projects', projectId, 'sections'] as const,
};

export function useSections(projectId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: sectionKeys.byProject(projectId),
    enabled: enabled && !!projectId,
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/sections', {
          params: { path: { project_id: projectId } },
        })
      ).data!.data,
  });
}

/** Local reorder helper for optimistic moves. */
export function moveInList(
  list: Section[],
  id: string,
  afterId: string | null,
  beforeId: string | null,
): Section[] {
  const item = list.find((s) => s.id === id);
  if (!item) return list;
  const rest = list.filter((s) => s.id !== id);
  let index = rest.length;
  if (afterId) index = rest.findIndex((s) => s.id === afterId) + 1;
  else if (beforeId) index = rest.findIndex((s) => s.id === beforeId);
  return [...rest.slice(0, index), item, ...rest.slice(index)];
}

export function useSectionMutations(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const key = sectionKeys.byProject(projectId);
  const settle = () => qc.invalidateQueries({ queryKey: key });

  const create = useMutation({
    mutationFn: async (v: { name: string; afterId?: string | null; beforeId?: string | null }) =>
      (
        await api.POST('/api/v1/projects/{project_id}/sections', {
          params: { path: { project_id: projectId } },
          body: { name: v.name, after_id: v.afterId ?? null, before_id: v.beforeId ?? null },
        })
      ).data!,
    onSuccess: (res) => {
      qc.setQueryData<Section[]>(key, (old) =>
        old ? [...old, res.data].sort((a, b) => (a.position < b.position ? -1 : 1)) : old,
      );
    },
    onError: (e) => toastError(e, "Couldn't add the section"),
    onSettled: settle,
  });

  const rename = useMutation({
    mutationFn: async (v: { id: string; name: string }) =>
      (
        await api.PATCH('/api/v1/sections/{section_id}', {
          params: { path: { section_id: v.id } },
          body: { name: v.name },
        })
      ).data!,
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<Section[]>(key);
      qc.setQueryData<Section[]>(key, (old) => old?.map((s) => (s.id === v.id ? { ...s, name: v.name } : s)));
      return { prev };
    },
    onError: (e, _v, ctx) => {
      qc.setQueryData(key, ctx?.prev);
      toastError(e);
    },
    onSuccess: (res) => undoToast('Section renamed', res.meta),
    onSettled: settle,
  });

  const move = useMutation({
    mutationFn: async (v: { id: string; afterId: string | null; beforeId: string | null }) =>
      (
        await api.POST('/api/v1/sections/{section_id}/move', {
          params: { path: { section_id: v.id } },
          body: { after_id: v.afterId, before_id: v.beforeId },
        })
      ).data!,
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<Section[]>(key);
      qc.setQueryData<Section[]>(key, (old) => (old ? moveInList(old, v.id, v.afterId, v.beforeId) : old));
      return { prev };
    },
    onError: (e, _v, ctx) => {
      qc.setQueryData(key, ctx?.prev);
      toastError(e, "Couldn't move the section");
    },
    onSuccess: (res) => undoToast('Section moved', res.meta),
    onSettled: settle,
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      (
        await api.DELETE('/api/v1/sections/{section_id}', {
          params: { path: { section_id: id }, query: { tasks: 'move_to' } },
        })
      ).data!,
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<Section[]>(key);
      qc.setQueryData<Section[]>(key, (old) => old?.filter((s) => s.id !== id));
      return { prev };
    },
    onError: (e, _v, ctx) => {
      qc.setQueryData(key, ctx?.prev);
      toastError(e);
    },
    onSuccess: (res) => undoToast('Section deleted', res.meta),
    onSettled: settle,
  });

  return { create, rename, move, remove };
}
