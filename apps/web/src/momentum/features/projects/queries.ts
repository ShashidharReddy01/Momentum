import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type Project = components['schemas']['ProjectOut'];
export type ProjectDetail = components['schemas']['ProjectDetailOut'];
export type ProjectCreate = components['schemas']['ProjectCreateIn'];
export type ProjectPatch = components['schemas']['ProjectPatchIn'];

export const projectKeys = {
  all: ['projects'] as const,
  list: (teamId?: string, archived = false) => ['projects', 'list', teamId ?? 'all', archived] as const,
  detail: (id: string) => ['projects', 'detail', id] as const,
  favorites: ['projects', 'favorites'] as const,
};

export function useProjects(opts: { teamId?: string; archived?: boolean } = {}) {
  const api = useApi();
  return useQuery({
    queryKey: projectKeys.list(opts.teamId, opts.archived),
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects', {
          params: { query: { ...(opts.teamId ? { team_id: opts.teamId } : {}), archived: !!opts.archived } },
        })
      ).data!.data,
  });
}

export function useFavorites() {
  const api = useApi();
  return useQuery({
    queryKey: projectKeys.favorites,
    queryFn: async () => (await api.GET('/api/v1/favorites')).data!.data,
  });
}

export function useProject(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: projectKeys.detail(id),
    queryFn: async () =>
      (await api.GET('/api/v1/projects/{project_id}', { params: { path: { project_id: id } } })).data!,
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: projectKeys.all });
}

export function useCreateProject() {
  const api = useApi();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (body: ProjectCreate) => (await api.POST('/api/v1/projects', { body })).data!,
    onSuccess: () => invalidate(),
    onError: (e) => toastError(e, "Couldn't create the project"),
  });
}

export function useUpdateProject(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  return useMutation({
    mutationFn: async (patch: ProjectPatch) =>
      (
        await api.PATCH('/api/v1/projects/{project_id}', {
          params: { path: { project_id: id } },
          body: patch,
        })
      ).data!,
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: projectKeys.detail(id) });
      const prev = qc.getQueryData<ProjectDetail>(projectKeys.detail(id));
      if (prev)
        qc.setQueryData<ProjectDetail>(projectKeys.detail(id), { ...prev, ...patch } as ProjectDetail);
      return { prev };
    },
    onError: (e, _p, ctx) => {
      if (ctx?.prev) qc.setQueryData(projectKeys.detail(id), ctx.prev);
      toastError(e, "Couldn't update the project");
    },
    onSuccess: (res) => undoToast('Project updated', res.meta),
    onSettled: () => qc.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

export function useProjectLifecycle(id: string) {
  const api = useApi();
  const invalidate = useInvalidate();
  const undoToast = useUndoToast();
  const path = { project_id: id };
  const archive = useMutation({
    mutationFn: async (archived: boolean) =>
      archived
        ? (await api.POST('/api/v1/projects/{project_id}/archive', { params: { path } })).data!
        : (await api.POST('/api/v1/projects/{project_id}/unarchive', { params: { path } })).data!,
    onSuccess: (res, archived) => {
      undoToast(archived ? 'Project archived' : 'Project restored from archive', res.meta);
      void invalidate();
    },
    onError: (e) => toastError(e),
  });
  const remove = useMutation({
    mutationFn: async () => (await api.DELETE('/api/v1/projects/{project_id}', { params: { path } })).data!,
    onSuccess: (res) => {
      undoToast('Project deleted', res.meta);
      void invalidate();
    },
    onError: (e) => toastError(e),
  });
  return { archive, remove };
}

export function useToggleFavorite() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { id: string; favorite: boolean }) =>
      v.favorite
        ? (
            await api.PUT('/api/v1/favorites/projects/{project_id}', {
              params: { path: { project_id: v.id } },
            })
          ).data!
        : (
            await api.DELETE('/api/v1/favorites/projects/{project_id}', {
              params: { path: { project_id: v.id } },
            })
          ).data!,
    onMutate: async (v) => {
      const key = projectKeys.detail(v.id);
      const prev = qc.getQueryData<ProjectDetail>(key);
      if (prev) qc.setQueryData<ProjectDetail>(key, { ...prev, is_favorite: v.favorite });
      return { prev };
    },
    onError: (e, v, ctx) => {
      if (ctx?.prev) qc.setQueryData(projectKeys.detail(v.id), ctx.prev);
      toastError(e);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: projectKeys.all }),
  });
}
