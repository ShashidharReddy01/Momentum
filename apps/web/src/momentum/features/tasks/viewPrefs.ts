import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';

/**
 * One saved-prefs record per (user, project): the list's filter/sort/group state (owned by
 * `useListView`, `features/tasks/useListView.ts`) plus `view` — which tab this user last had
 * open (owned by `useLastView` below). Both hooks read and write the *same* query key so a
 * save from either side merges onto the other's latest fields instead of overwriting them.
 */
export type StoredViewPrefs = components['schemas']['ProjectViewPrefs'];
export type ViewKey = NonNullable<StoredViewPrefs['view']>;

export const viewPrefsKey = (projectId: string) => ['view-prefs', projectId] as const;

const EMPTY_LIST_PREFS: Omit<StoredViewPrefs, 'view'> = {
  assignees: [],
  due: 'any',
  show_completed: false,
  sort: 'manual',
  group: 'section',
};

/** S2.2.3: the tab (list/board/calendar/…) this user last had open for a project, restored on
 * revisit. Falls back to the project's `default_view` (set by a project admin) for a project
 * this user has never had an opinion on. */
export function useLastView(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const key = viewPrefsKey(projectId);
  const prefs = useQuery({
    queryKey: key,
    queryFn: async () =>
      (await api.GET('/api/v1/me/prefs/views/{project_id}', { params: { path: { project_id: projectId } } }))
        .data as StoredViewPrefs,
    staleTime: Infinity,
    retry: false,
  });

  const save = useCallback(
    (view: ViewKey) => {
      const current = qc.getQueryData<StoredViewPrefs>(key);
      if (current?.view === view) return;
      const next: StoredViewPrefs = { ...(current ?? EMPTY_LIST_PREFS), view };
      qc.setQueryData(key, next);
      // Best effort: a failed save only means the tab isn't remembered next time.
      void api
        .PUT('/api/v1/me/prefs/views/{project_id}', {
          params: { path: { project_id: projectId } },
          body: next,
        })
        .catch(() => undefined);
    },
    [api, key, projectId, qc],
  );

  return { lastView: prefs.data?.view ?? null, ready: !prefs.isPending, save };
}
