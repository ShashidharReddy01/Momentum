import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type Team = components['schemas']['TeamOut'];
export type TeamDetail = components['schemas']['TeamDetailOut'];
export type TeamCreate = components['schemas']['TeamCreateIn'];
export type TeamPatch = components['schemas']['TeamPatchIn'];

export const teamKeys = {
  all: ['teams'] as const,
  list: () => ['teams', 'list'] as const,
  detail: (id: string) => ['teams', 'detail', id] as const,
};

export function useTeams() {
  const api = useApi();
  return useQuery({
    queryKey: teamKeys.list(),
    queryFn: async () => (await api.GET('/api/v1/teams')).data!.data,
  });
}

export function useTeam(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: teamKeys.detail(id),
    queryFn: async () =>
      (await api.GET('/api/v1/teams/{team_id}', { params: { path: { team_id: id } } })).data!,
  });
}

function useInvalidateTeams() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: teamKeys.all });
}

export function useCreateTeam() {
  const api = useApi();
  const invalidate = useInvalidateTeams();
  return useMutation({
    mutationFn: async (body: TeamCreate) => (await api.POST('/api/v1/teams', { body })).data!,
    onSuccess: () => invalidate(),
    onError: (e) => toastError(e, "Couldn't create the team"),
  });
}

export function useUpdateTeam(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  return useMutation({
    mutationFn: async (patch: TeamPatch) =>
      (await api.PATCH('/api/v1/teams/{team_id}', { params: { path: { team_id: id } }, body: patch })).data!,
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: teamKeys.detail(id) });
      const prev = qc.getQueryData<TeamDetail>(teamKeys.detail(id));
      if (prev) qc.setQueryData<TeamDetail>(teamKeys.detail(id), { ...prev, ...patch } as TeamDetail);
      return { prev };
    },
    onError: (e, _p, ctx) => {
      if (ctx?.prev) qc.setQueryData(teamKeys.detail(id), ctx.prev);
      toastError(e, "Couldn't update the team");
    },
    onSuccess: (res) => undoToast('Team updated', res.meta),
    onSettled: () => qc.invalidateQueries({ queryKey: teamKeys.all }),
  });
}

export function useDeleteTeam(id: string) {
  const api = useApi();
  const invalidate = useInvalidateTeams();
  const undoToast = useUndoToast();
  return useMutation({
    mutationFn: async () =>
      (await api.DELETE('/api/v1/teams/{team_id}', { params: { path: { team_id: id } } })).data!,
    onSuccess: (res) => {
      undoToast('Team deleted', res.meta);
      void invalidate();
    },
    onError: (e) => toastError(e, "Couldn't delete the team"),
  });
}

export function useTeamMembers(teamId: string) {
  const api = useApi();
  const invalidate = useInvalidateTeams();
  const undoToast = useUndoToast();
  const path = { team_id: teamId };
  const add = useMutation({
    mutationFn: async (userId: string) =>
      (
        await api.POST('/api/v1/teams/{team_id}/members', {
          params: { path },
          body: { user_id: userId, role: 'member' },
        })
      ).data!,
    onSuccess: (res) => {
      undoToast('Member added', res.meta);
      void invalidate();
    },
    onError: (e) => toastError(e),
  });
  const setRole = useMutation({
    mutationFn: async (v: { userId: string; role: 'lead' | 'member' }) =>
      (
        await api.PATCH('/api/v1/teams/{team_id}/members/{user_id}', {
          params: { path: { ...path, user_id: v.userId } },
          body: { role: v.role },
        })
      ).data!,
    onSuccess: (res) => {
      undoToast('Role changed', res.meta);
      void invalidate();
    },
    onError: (e) => toastError(e),
  });
  const remove = useMutation({
    mutationFn: async (userId: string) =>
      (
        await api.DELETE('/api/v1/teams/{team_id}/members/{user_id}', {
          params: { path: { ...path, user_id: userId } },
        })
      ).data!,
    onSuccess: (res) => {
      undoToast('Member removed', res.meta);
      void invalidate();
    },
    onError: (e) => toastError(e),
  });
  return { add, setRole, remove };
}
