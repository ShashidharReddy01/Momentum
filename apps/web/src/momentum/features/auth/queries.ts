import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';

export type Me = components['schemas']['MeOut'];
export type UserSummary = components['schemas']['UserOut'];

export const authKeys = {
  me: ['me'] as const,
  devUsers: ['dev', 'users'] as const,
};

export function useMe() {
  const api = useApi();
  return useQuery({
    queryKey: authKeys.me,
    queryFn: async () => (await api.GET('/api/v1/me')).data as Me,
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export function useDevUsers(enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: authKeys.devUsers,
    queryFn: async () => (await api.GET('/api/v1/dev/users')).data as UserSummary[],
    enabled,
  });
}

export function useDevLogin() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) =>
      (await api.POST('/api/v1/dev/login', { body: { user_id: userId } })).data as UserSummary,
    onSuccess: () => qc.removeQueries({ queryKey: authKeys.me }),
  });
}

export function useLogout() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.POST('/api/v1/auth/logout')).data as { redirect_url: string },
    onSuccess: (res) => {
      qc.clear();
      window.location.assign(res.redirect_url);
    },
  });
}
