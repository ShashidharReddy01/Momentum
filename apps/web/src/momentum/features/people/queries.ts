import { useQuery } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';

export type Person = components['schemas']['UserOut'];

/** Which agent accounts to include (S5.2.1): the enabled agents that act when assigned or
 * mentioned (pickers), or every agent (to show who a task is assigned to). People only when
 * omitted. */
export type AgentFilter = 'assigned' | 'mentioned' | 'all';

export function usePeople(q = '', agents?: AgentFilter) {
  const api = useApi();
  return useQuery({
    queryKey: agents ? ['people', q, agents] : ['people', q],
    queryFn: async () =>
      (
        await api.GET('/api/v1/users', {
          // unfiltered: everyone (pickers filter locally); 1,000 leaves room well past ~150 people
          params: { query: { ...(q ? { q, limit: 50 } : { limit: 1000 }), ...(agents ? { agents } : {}) } },
        })
      ).data!.data,
    staleTime: 60_000,
  });
}
