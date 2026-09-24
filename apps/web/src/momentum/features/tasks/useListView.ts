import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router';
import { useApi } from '@/providers/api';
import { DEFAULT_VIEW, isDefaultView, viewFromParams, viewToParams, type ListView } from './view';
import { viewPrefsKey, type StoredViewPrefs } from './viewPrefs';

const SAVE_DELAY_MS = 600;

// The stored record's filter/sort/group fields are typed optional (they carry server-side
// defaults, so the OpenAPI schema doesn't require them), but `view` on it never appears in a
// `ListView` at all — it's a different concern (see the module doc above). This fills in the
// defaults explicitly rather than casting, so a genuinely missing field (an old saved record,
// say) still behaves correctly rather than just satisfying the compiler.
const asListView = (v: StoredViewPrefs | undefined): ListView | undefined =>
  v && {
    assignees: v.assignees ?? DEFAULT_VIEW.assignees,
    due: v.due ?? DEFAULT_VIEW.due,
    show_completed: v.show_completed ?? DEFAULT_VIEW.show_completed,
    sort: v.sort ?? DEFAULT_VIEW.sort,
    group: v.group ?? DEFAULT_VIEW.group,
  };

/**
 * The list view for a project. Source of truth: URL params when present (shareable links),
 * otherwise the user's saved prefs. Changes update the URL (replace) and are saved (debounced).
 *
 * The saved record also carries `view` — which tab (list/board/calendar/…) this user last had
 * open, owned by `useLastView` — so every save here reads the latest cached record first and
 * only overwrites the filter/sort/group fields, never `view`.
 */
export function useListView(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const fromUrl = useMemo(() => viewFromParams(params), [params]);
  const key = useMemo(() => viewPrefsKey(projectId), [projectId]);
  const prefs = useQuery({
    queryKey: key,
    queryFn: async () =>
      (await api.GET('/api/v1/me/prefs/views/{project_id}', { params: { path: { project_id: projectId } } }))
        .data as StoredViewPrefs,
    staleTime: Infinity,
    retry: false,
  });
  const fromPrefs = asListView(prefs.data);
  const view: ListView = fromUrl ?? fromPrefs ?? DEFAULT_VIEW;
  const ready = fromUrl !== null || !prefs.isPending;

  // Reflect restored prefs in the URL once, so "copy link" shares what you see.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || !ready) return;
    restored.current = true;
    if (!fromUrl && fromPrefs && !isDefaultView(fromPrefs)) {
      setParams((p) => viewToParams(fromPrefs, p), { replace: true });
    }
  }, [ready, fromUrl, fromPrefs, setParams]);

  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const setView = useCallback(
    (next: ListView) => {
      setParams((p) => viewToParams(next, p), { replace: true });
      // Merge onto the latest cached record so a filter/sort/group change never wipes the
      // `view` tab useLastView saved there.
      const merged: StoredViewPrefs = { ...(qc.getQueryData<StoredViewPrefs>(key) ?? prefs.data), ...next };
      qc.setQueryData(key, merged);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        // Best effort: a failed save only means the view isn't remembered next time.
        void api
          .PUT('/api/v1/me/prefs/views/{project_id}', {
            params: { path: { project_id: projectId } },
            body: merged,
          })
          .catch(() => undefined);
      }, SAVE_DELAY_MS);
    },
    [api, key, prefs.data, projectId, qc, setParams],
  );

  return { view, setView, ready };
}
