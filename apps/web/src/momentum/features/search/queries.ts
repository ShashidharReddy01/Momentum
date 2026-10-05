import { useQuery } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';

export type SearchResults = components['schemas']['SearchResultsOut'];
export type TaskHit = components['schemas']['TaskHit'];
export type ProjectHit = components['schemas']['ProjectHit'];
export type PersonHit = components['schemas']['PersonHit'];
export type CommentHit = components['schemas']['CommentHit'];

export interface SearchFilters {
  type?: string;
  project_id?: string;
  assignee_id?: string;
  completed?: boolean;
  /** S7.4.1: custom-field filters (`<field id>:<op>[:<arg>]`); with these, no words are needed */
  field?: string[];
  limit?: number;
}

/** S2.6.2: `GET /search`, permission-filtered in SQL. `q` under 2 chars skips the request
 * entirely (nothing useful to match, and it keeps every keystroke of a short query from firing
 * a network call). */
export function useSearch(q: string, filters: SearchFilters = {}) {
  const api = useApi();
  const clean = q.trim();
  return useQuery({
    queryKey: ['search', clean, filters],
    queryFn: async () =>
      (
        await api.GET('/api/v1/search', {
          params: { query: { q: clean, ...filters } },
        })
      ).data!,
    enabled: clean.length >= 2 || !!filters.field?.length,
    staleTime: 10_000,
  });
}
