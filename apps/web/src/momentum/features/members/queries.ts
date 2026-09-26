import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type Member = components['schemas']['UserOut'];
export type UserInvite = components['schemas']['UserInviteIn'];
export type OnboardingStatus = components['schemas']['OnboardingStatusOut'];

export const memberKeys = {
  list: ['members'] as const,
  onboarding: ['onboarding'] as const,
};

export function useMembers() {
  const api = useApi();
  return useQuery({
    queryKey: memberKeys.list,
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
