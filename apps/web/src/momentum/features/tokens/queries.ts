import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type ApiToken = components['schemas']['ApiTokenOut'];
export type NewToken = components['schemas']['ApiTokenIn'];

const key = ['me', 'tokens'] as const;

export function useMyTokens() {
  const api = useApi();
  return useQuery({ queryKey: key, queryFn: async () => (await api.GET('/api/v1/me/tokens')).data!.data });
}

export function useCreateToken() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: NewToken) => (await api.POST('/api/v1/me/tokens', { body })).data!,
    onSuccess: () => void qc.invalidateQueries({ queryKey: key }),
    onError: (e) => toastError(e, "Couldn't create the token"),
  });
}

export function useRevokeToken() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      (await api.DELETE('/api/v1/me/tokens/{token_id}', { params: { path: { token_id: id } } })).data!,
    onSuccess: () => void qc.invalidateQueries({ queryKey: key }),
    onError: (e) => toastError(e, "Couldn't revoke the token"),
  });
}
