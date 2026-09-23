import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router';
import { useApi } from '@/providers/api';
import { DEFAULT_VIEW, isDefaultView, viewFromParams, viewToParams, type ListView } from './view';

const SAVE_DELAY_MS = 600;

/**
 * The list view for a project. Source of truth: URL params when present (shareable links),
 * otherwise the user's saved prefs. Changes update the URL (replace) and are saved (debounced).
 */
export function useListView(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const fromUrl = useMemo(() => viewFromParams(params), [params]);
  const key = useMemo(() => ['view-prefs', projectId] as const, [projectId]);
  const prefs = useQuery({
    queryKey: key,
    queryFn: async () =>
      (await api.GET('/api/v1/me/prefs/views/{project_id}', { params: { path: { project_id: projectId } } }))
        .data as ListView,
    staleTime: Infinity,
    retry: false,
  });
  const view: ListView = fromUrl ?? prefs.data ?? DEFAULT_VIEW;
  const ready = fromUrl !== null || !prefs.isPending;

  // Reflect restored prefs in the URL once, so "copy link" shares what you see.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || !ready) return;
    restored.current = true;
    if (!fromUrl && prefs.data && !isDefaultView(prefs.data)) {
      setParams((p) => viewToParams(prefs.data!, p), { replace: true });
    }
  }, [ready, fromUrl, prefs.data, setParams]);

  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const setView = useCallback(
    (next: ListView) => {
      setParams((p) => viewToParams(next, p), { replace: true });
      qc.setQueryData(key, next);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        // Best effort: a failed save only means the view isn't remembered next time.
        void api
          .PUT('/api/v1/me/prefs/views/{project_id}', {
            params: { path: { project_id: projectId } },
            body: next,
          })
          .catch(() => undefined);
      }, SAVE_DELAY_MS);
    },
    [api, key, projectId, qc, setParams],
  );

  return { view, setView, ready };
}
