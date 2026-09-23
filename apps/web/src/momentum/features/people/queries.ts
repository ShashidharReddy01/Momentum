import { useQuery } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';

export type Person = components['schemas']['UserOut'];

export function usePeople(q = '') {
  const api = useApi();
  return useQuery({
    queryKey: ['people', q],
    queryFn: async () =>
      (await api.GET('/api/v1/users', { params: { query: q ? { q, limit: 50 } : { limit: 200 } } })).data!
        .data,
    staleTime: 60_000,
  });
}
