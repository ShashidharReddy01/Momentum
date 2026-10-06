import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { ApiError } from '@/lib/api/errors';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import { portfolioKeys } from './queries';

/** Phase 7.5 (spec §5.2-§5.6): portfolio v2 reads and writes. Rows are computed on the server
 * (every column, filters, grouping, sort); the client only renders and asks. */

export type RowsOut = components['schemas']['PortfolioRowsOut'];
export type RowV2 = components['schemas']['PortfolioRowOut'];
export type RowGroup = components['schemas']['PortfolioGroupOut'];
export type ColumnV2 = components['schemas']['ColumnOut'];
export type SavedView = components['schemas']['PortfolioViewOut'];
export type ViewFilters = components['schemas']['ViewFiltersIn'];
export type PortfolioMember = components['schemas']['PortfolioMemberOut'];
export type Readiness = components['schemas']['ReadinessOut'];
export type PortfolioSettings = components['schemas']['PortfolioConfigIn'];
export type PortfolioRule = components['schemas']['PortfolioRuleIn'];
export type SortSpec = { key: string; dir: 'asc' | 'desc' };

export interface RowsParams {
  viewId?: string | null;
  filters?: Partial<ViewFilters> | null;
  groupBy?: string | null;
  sort?: SortSpec[] | null;
}

export const v2Keys = {
  rows: (id: string, p: RowsParams) => ['portfolios', id, 'rows', p] as const,
  rowsAll: (id: string) => ['portfolios', id, 'rows'] as const,
  views: (id: string) => ['portfolios', id, 'views'] as const,
  members: (id: string) => ['portfolios', id, 'members'] as const,
  summaries: ['portfolios', 'summaries'] as const,
};

/** Query params for the rows and CSV endpoints. `undefined` leaves the saved view's choice. */
export function rowsQuery(p: RowsParams): Record<string, string> {
  const q: Record<string, string> = {};
  if (p.viewId) q.view_id = p.viewId;
  if (p.filters) q.filters = JSON.stringify(p.filters);
  if (p.groupBy !== undefined) q.group_by = p.groupBy ?? '';
  if (p.sort) q.sort = p.sort.map((s) => `${s.key}:${s.dir}`).join(',');
  return q;
}

export function usePortfolioRows(id: string, params: RowsParams) {
  const api = useApi();
  return useQuery({
    queryKey: v2Keys.rows(id, params),
    placeholderData: (prev) => prev, // re-sorting keeps the table on screen
    queryFn: async () =>
      (
        await api.GET('/api/v1/portfolios/{portfolio_id}/rows', {
          params: { path: { portfolio_id: id }, query: rowsQuery(params) },
        })
      ).data!,
  });
}

export function usePortfolioSummaries() {
  const api = useApi();
  return useQuery({
    queryKey: v2Keys.summaries,
    queryFn: async () =>
      (await api.GET('/api/v1/portfolios', { params: { query: { summaries: true } } })).data!.data,
  });
}

function useRefresh(id: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: portfolioKeys.detail(id) });
    void qc.invalidateQueries({ queryKey: v2Keys.rowsAll(id) });
    void qc.invalidateQueries({ queryKey: portfolioKeys.list });
    void qc.invalidateQueries({ queryKey: v2Keys.summaries });
  };
}

/** Settings and conversion (editors). Each change offers Undo. */
export function usePortfolioSettings(id: string) {
  const api = useApi();
  const undoToast = useUndoToast();
  const refresh = useRefresh(id);
  const path = { portfolio_id: id };
  const configure = useMutation({
    mutationFn: async (body: PortfolioSettings) =>
      (await api.PATCH('/api/v1/portfolios/{portfolio_id}/settings', { params: { path }, body })).data!,
    onSuccess: (res) => undoToast('Portfolio settings saved', res.meta, refresh),
    onError: (e) => toastError(e, "Couldn't save the settings"),
    onSettled: refresh,
  });
  const convert = useMutation({
    mutationFn: async (body: { kind: 'manual' | 'rule'; rule?: PortfolioRule | null }) =>
      (await api.POST('/api/v1/portfolios/{portfolio_id}/convert', { params: { path }, body })).data!,
    onSuccess: (res) =>
      undoToast(
        res.data.kind === 'rule' ? 'Projects now come from the rule' : 'Projects are now picked by hand',
        res.meta,
        refresh,
      ),
    onError: (e) => toastError(e, "Couldn't change how projects are picked"),
    onSettled: refresh,
  });
  return { configure, convert };
}

export function usePortfolioViews(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: v2Keys.views(id),
    queryFn: async () =>
      (
        await api.GET('/api/v1/portfolios/{portfolio_id}/views', {
          params: { path: { portfolio_id: id } },
        })
      ).data!.data,
  });
}

export function useViewMutations(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const path = { portfolio_id: id };
  const refresh = () => void qc.invalidateQueries({ queryKey: v2Keys.views(id) });
  const create = useMutation({
    mutationFn: async (body: components['schemas']['PortfolioViewIn']) =>
      (await api.POST('/api/v1/portfolios/{portfolio_id}/views', { params: { path }, body })).data!,
    onSuccess: (res) => undoToast(`View “${res.data.name}” saved`, res.meta, refresh),
    onError: (e) => toastError(e, "Couldn't save the view"),
    onSettled: refresh,
  });
  const update = useMutation({
    mutationFn: async (v: { viewId: string; patch: components['schemas']['PortfolioViewPatchIn'] }) =>
      (
        await api.PATCH('/api/v1/portfolios/{portfolio_id}/views/{view_id}', {
          params: { path: { ...path, view_id: v.viewId } },
          body: v.patch,
        })
      ).data!,
    onSuccess: (res) => undoToast(`View “${res.data.name}” updated`, res.meta, refresh),
    onError: (e) => toastError(e, "Couldn't update the view"),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: async (viewId: string) =>
      (
        await api.DELETE('/api/v1/portfolios/{portfolio_id}/views/{view_id}', {
          params: { path: { ...path, view_id: viewId } },
        })
      ).data!,
    onSuccess: (res) => undoToast('View deleted', res.meta, refresh),
    onError: (e) => toastError(e, "Couldn't delete the view"),
    onSettled: refresh,
  });
  return { create, update, remove };
}

export function usePortfolioMembers(id: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: v2Keys.members(id),
    enabled,
    queryFn: async () =>
      (
        await api.GET('/api/v1/portfolios/{portfolio_id}/members', {
          params: { path: { portfolio_id: id } },
        })
      ).data!.data,
  });
}

export function useMemberMutations(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const refresh = () => void qc.invalidateQueries({ queryKey: v2Keys.members(id) });
  const set = useMutation({
    mutationFn: async (v: { userId: string; role: 'editor' | 'viewer' }) =>
      (
        await api.PUT('/api/v1/portfolios/{portfolio_id}/members/{user_id}', {
          params: { path: { portfolio_id: id, user_id: v.userId } },
          body: { role: v.role },
        })
      ).data!,
    onSuccess: (res) => undoToast('Member saved', res.meta, refresh),
    onError: (e) => toastError(e, "Couldn't change the member"),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: async (userId: string) =>
      (
        await api.DELETE('/api/v1/portfolios/{portfolio_id}/members/{user_id}', {
          params: { path: { portfolio_id: id, user_id: userId } },
        })
      ).data!,
    onSuccess: (res) => undoToast('Member removed', res.meta, refresh),
    onError: (e) => toastError(e, "Couldn't remove the member"),
    onSettled: refresh,
  });
  return { set, remove };
}

/** The checklist a gate would show, from a 409 `gate_not_met` (null for any other error). */
export function gateChecklist(e: unknown): Readiness | null {
  if (e instanceof ApiError && e.code === 'gate_not_met') {
    const r = (e.problem as unknown as { readiness?: Readiness }).readiness;
    return r ?? null;
  }
  return null;
}

/** A board move: sets the stage (project editors). A gate that isn't met throws a 409 whose
 * checklist the caller shows; `override` moves anyway and is recorded in the activity. */
export function useMoveStage(id: string) {
  const api = useApi();
  const undoToast = useUndoToast();
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: async (v: { projectId: string; to: string; override?: boolean; label: string }) =>
      (
        await api.POST('/api/v1/portfolios/{portfolio_id}/projects/{project_id}/stage', {
          params: { path: { portfolio_id: id, project_id: v.projectId } },
          body: { to: v.to, override: v.override ?? false },
        })
      ).data!,
    onSuccess: (res, v) =>
      undoToast(`Moved to ${v.label}${v.override ? ' (gate overridden)' : ''}`, res.meta, refresh),
    onError: (e) => {
      if (!gateChecklist(e)) toastError(e, "Couldn't move the project");
    },
    onSettled: refresh,
  });
}

export function useBulkSetField(id: string) {
  const api = useApi();
  const undoToast = useUndoToast();
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: async (body: { project_ids: string[]; field_id: string; value: unknown }) =>
      (
        await api.POST('/api/v1/portfolios/{portfolio_id}/bulk-set-field', {
          params: { path: { portfolio_id: id } },
          body,
        })
      ).data!,
    onSuccess: (res) => {
      const { updated, skipped } = res.data;
      const note = skipped ? ` (${skipped} skipped: you can't edit them)` : '';
      undoToast(`Updated ${updated} project${updated === 1 ? '' : 's'}${note}`, res.meta, refresh);
    },
    onError: (e) => toastError(e, "Couldn't set the field"),
    onSettled: refresh,
  });
}

/** One project field on one row (inline edit). */
export function useSetRowField(id: string) {
  const api = useApi();
  const undoToast = useUndoToast();
  const refresh = useRefresh(id);
  return useMutation({
    mutationFn: async (v: { projectId: string; fieldId: string; value: unknown; name: string }) =>
      (
        await api.PUT('/api/v1/projects/{project_id}/project-field-values/{field_id}', {
          params: { path: { project_id: v.projectId, field_id: v.fieldId } },
          body: { value: v.value },
        })
      ).data!,
    onSuccess: (res, v) => {
      if (res.meta.activity_id) undoToast(`${v.name} updated`, res.meta, refresh);
    },
    onError: (e) => toastError(e, "Couldn't save that"),
    onSettled: refresh,
  });
}
