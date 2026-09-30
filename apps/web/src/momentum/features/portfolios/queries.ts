import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type Portfolio = components['schemas']['PortfolioOut'];
export type PortfolioDetail = components['schemas']['PortfolioDetailOut'];
export type PortfolioRow = components['schemas']['PortfolioProjectRow'];
export type StatusUpdateIn = components['schemas']['StatusUpdateIn'];
export type PortfolioLine = components['schemas']['PortfolioLineOut'];

export const portfolioKeys = {
  all: ['portfolios'] as const,
  list: ['portfolios', 'list'] as const,
  detail: (id: string) => ['portfolios', id] as const,
  statuses: (id: string) => ['portfolios', id, 'status-updates'] as const,
  lines: (id: string) => ['portfolios', id, 'lines'] as const,
};

export function usePortfolios() {
  const api = useApi();
  return useQuery({
    queryKey: portfolioKeys.list,
    queryFn: async () => (await api.GET('/api/v1/portfolios')).data!.data,
  });
}

export function usePortfolio(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: portfolioKeys.detail(id),
    queryFn: async () =>
      (await api.GET('/api/v1/portfolios/{portfolio_id}', { params: { path: { portfolio_id: id } } })).data!,
  });
}

export function usePortfolioStatuses(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: portfolioKeys.statuses(id),
    queryFn: async () =>
      (
        await api.GET('/api/v1/portfolios/{portfolio_id}/status-updates', {
          params: { path: { portfolio_id: id } },
        })
      ).data!.data,
  });
}

/** ✦ one line per visible project (S6.2.2); recomputed when the table changes. */
export function usePortfolioLines(id: string, version: number | undefined, enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: [...portfolioKeys.lines(id), version] as const,
    enabled: enabled && version !== undefined,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: async () =>
      (
        await api.POST('/api/v1/ai/portfolios/{portfolio_id}/lines', {
          params: { path: { portfolio_id: id } },
        })
      ).data!.lines,
  });
}

export function useCreatePortfolio() {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  return useMutation({
    mutationFn: async (body: { name: string; description?: string | null }) =>
      (await api.POST('/api/v1/portfolios', { body })).data!,
    onSuccess: (res) => {
      undoToast(
        'Portfolio created',
        res.meta,
        () => void qc.invalidateQueries({ queryKey: portfolioKeys.all }),
      );
      void qc.invalidateQueries({ queryKey: portfolioKeys.list });
    },
    onError: (e) => toastError(e, "Couldn't create the portfolio"),
  });
}

/** Edits to one portfolio; each returns the fresh detail, and offers Undo. */
export function usePortfolioMutations(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const path = { portfolio_id: id };
  const refresh = () => void qc.invalidateQueries({ queryKey: portfolioKeys.all });
  const settle = (message: string) => ({
    onSuccess: (res: { data: PortfolioDetail; meta: components['schemas']['MutationMeta'] }) => {
      qc.setQueryData(portfolioKeys.detail(id), res.data);
      undoToast(message, res.meta, refresh);
      void qc.invalidateQueries({ queryKey: portfolioKeys.list });
    },
    onError: (e: unknown) => toastError(e, "Couldn't update the portfolio"),
  });

  const rename = useMutation({
    mutationFn: async (body: { name?: string; description?: string | null }) =>
      (await api.PATCH('/api/v1/portfolios/{portfolio_id}', { params: { path }, body })).data!,
    ...settle('Portfolio updated'),
  });
  const addProject = useMutation({
    mutationFn: async (projectId: string) =>
      (
        await api.POST('/api/v1/portfolios/{portfolio_id}/projects', {
          params: { path },
          body: { project_id: projectId },
        })
      ).data!,
    ...settle('Project added'),
  });
  const removeProject = useMutation({
    mutationFn: async (projectId: string) =>
      (
        await api.DELETE('/api/v1/portfolios/{portfolio_id}/projects/{project_id}', {
          params: { path: { ...path, project_id: projectId } },
        })
      ).data!,
    ...settle('Project removed'),
  });
  const draft = useMutation({
    mutationFn: async () =>
      (await api.GET('/api/v1/portfolios/{portfolio_id}/status-draft', { params: { path } })).data!.draft,
    onError: (e) => toastError(e, "Couldn't draft the check-in"),
  });
  const postStatus = useMutation({
    mutationFn: async (body: StatusUpdateIn) =>
      (await api.POST('/api/v1/portfolios/{portfolio_id}/status-updates', { params: { path }, body })).data!,
    onSuccess: (res) => {
      undoToast('Check-in posted', res.meta, refresh);
      refresh();
    },
    onError: (e) => toastError(e, "Couldn't post the check-in"),
  });
  return { rename, addProject, removeProject, draft, postStatus };
}
