import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type Member = components['schemas']['UserOut'];
export type UserInvite = components['schemas']['UserInviteIn'];
export type OnboardingStatus = components['schemas']['OnboardingStatusOut'];

export const memberKeys = {
  list: ['members'] as const,
  onboarding: ['onboarding'] as const,
};

/** The full roster, invited and disabled included (admin only: anyone else gets a 403). */
export function useMembers(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: memberKeys.list,
    enabled,
    queryFn: async () => (await api.GET('/api/v1/users/members')).data!.data,
  });
}

export function useInviteMember() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: UserInvite) => (await api.POST('/api/v1/users/invite', { body })).data!,
    onSuccess: () => void qc.invalidateQueries({ queryKey: memberKeys.list }),
    onError: (e) => toastError(e, "Couldn't send that invite"),
  });
}

/** S7.5.4: an admin changes a role or disables / re-enables someone (undoable). */
export function useUpdateMember() {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const refresh = () => void qc.invalidateQueries({ queryKey: memberKeys.list });
  return useMutation({
    mutationFn: async (v: {
      id: string;
      role?: Member['role'];
      status?: 'active' | 'disabled';
      message: string;
    }) =>
      (
        await api.PATCH('/api/v1/users/{user_id}', {
          params: { path: { user_id: v.id } },
          body: {
            ...(v.role ? { role: v.role as 'admin' | 'member' | 'guest' } : {}),
            ...(v.status ? { status: v.status } : {}),
          },
        })
      ).data!,
    onSuccess: (res, v) => {
      refresh();
      undoToast(v.message, res.meta, refresh);
    },
    onError: (e) => toastError(e, "Couldn't change that member"),
  });
}

/** S7.5.4: hand a member's open tasks and owned projects to someone else. */
export function useTransferWork() {
  const api = useApi();
  return useMutation({
    mutationFn: async (v: { from: string; to: string }) =>
      (
        await api.POST('/api/v1/users/{user_id}/transfer', {
          params: { path: { user_id: v.from } },
          body: { to_user_id: v.to },
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't hand the work on"),
  });
}

export function useOnboarding(opts: { enabled?: boolean } = {}) {
  const api = useApi();
  return useQuery({
    queryKey: memberKeys.onboarding,
    queryFn: async () => (await api.GET('/api/v1/me/onboarding')).data!,
    staleTime: 30_000,
    enabled: opts.enabled ?? true,
  });
}

export function useMarkOnboarding() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (patch: { used_command_palette?: boolean; dismissed?: boolean }) =>
      (await api.PATCH('/api/v1/me/onboarding', { body: patch })).data!,
    onSuccess: (data) => qc.setQueryData(memberKeys.onboarding, data),
  });
}
