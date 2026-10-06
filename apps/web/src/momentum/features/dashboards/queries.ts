import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type Dashboard = components['schemas']['DashboardOut'];
export type DashboardDetail = components['schemas']['DashboardDetailOut'];
export type ProjectDashboard = components['schemas']['ProjectDashboardOut'];
export type Widget = components['schemas']['WidgetOut'];
export type WidgetIn = components['schemas']['WidgetIn'];
export type WidgetKind = Widget['kind'];
/** A v1 tasks spec (S6.5.1). */
export type QuerySpec = components['schemas']['QuerySpec'];
/** Phase 7.5: what a widget stores, v1 or v2 (``entity`` says which question it asks). */
export type AnySpec = Widget['query_spec'];
export type SpecV2 = Exclude<AnySpec, QuerySpec>;
export type ProjectsSpec = components['schemas']['ProjectsSpec'];
export type StageSpec = components['schemas']['StageSpec'];
export type DashboardFilters = components['schemas']['DashboardFilters'];
export type DashboardTemplate = components['schemas']['DashboardTemplateOut'];
export type TemplatePreview = components['schemas']['TemplatePreviewOut'];
export type StageStat = components['schemas']['StageStatOut'];
export type TimelineItem = components['schemas']['TimelineItemOut'];
export type DrillProject = components['schemas']['DrillProjectOut'];
/** The kinds the v1 (tasks) editor builds. */
export type V1Kind = 'count' | 'bar' | 'donut' | 'line' | 'list';

export function isV1(spec: AnySpec): spec is QuerySpec {
  return spec.version !== 2;
}

/** Only the filters someone set (the API's shape carries every default). */
export function activeFilters(f: DashboardFilters | null | undefined): DashboardFilters | null {
  if (!f) return null;
  const out: Partial<DashboardFilters> = {};
  if (f.portfolio_id) out.portfolio_id = f.portfolio_id;
  if (f.period) out.period = f.period;
  if (f.period === 'custom') {
    out.period_from = f.period_from ?? null;
    out.period_to = f.period_to ?? null;
  }
  if (f.owner?.length) out.owner = f.owner;
  if (f.assignee?.length) out.assignee = f.assignee;
  if (f.fields?.length) out.fields = f.fields;
  return Object.keys(out).length ? (out as DashboardFilters) : null;
}
export type QueryResult = components['schemas']['QueryResultOut'];
export type GroupRow = components['schemas']['GroupOut'];
export type SeriesPoint = components['schemas']['PointOut'];
export type TaskRow = components['schemas']['TaskRowOut'];
export type Drill = components['schemas']['DrillOut'];
export type FilterName = components['schemas']['FilterNameOut'];
type Meta = components['schemas']['MutationMeta'];

export const dashboardKeys = {
  all: ['dashboards'] as const,
  list: ['dashboards', 'list'] as const,
  detail: (id: string) => ['dashboards', id] as const,
  project: (projectId: string) => ['dashboards', 'project', projectId] as const,
  portfolio: (portfolioId: string) => ['dashboards', 'portfolio', portfolioId] as const,
  pinned: ['dashboards', 'pinned'] as const,
  templates: ['dashboards', 'templates'] as const,
  /** every widget's numbers: invalidated together when the work underneath changes */
  data: ['dashboards', 'data'] as const,
};

/** Numbers age: a workspace dashboard has no single channel for "any task changed", so its
 * widgets refresh on focus and once a minute (each shows when it was computed). */
const DATA_REFRESH_MS = 60_000;

export function useDashboards() {
  const api = useApi();
  return useQuery({
    queryKey: dashboardKeys.list,
    queryFn: async () => (await api.GET('/api/v1/dashboards')).data!.data,
  });
}

export function useDashboard(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: dashboardKeys.detail(id),
    queryFn: async () =>
      (await api.GET('/api/v1/dashboards/{dashboard_id}', { params: { path: { dashboard_id: id } } })).data!,
  });
}

export function useProjectDashboard(projectId: string) {
  const api = useApi();
  return useQuery({
    queryKey: dashboardKeys.project(projectId),
    queryFn: async () =>
      (
        await api.GET('/api/v1/dashboards/project/{project_id}', {
          params: { path: { project_id: projectId } },
        })
      ).data!,
  });
}

/** A saved widget's numbers (as the viewer); `version` refetches after an edit. `filters` are
 * the viewer's own for this view (Phase 7.5); without them the dashboard's saved ones apply. */
export function useWidgetData(
  widgetId: string,
  version: number,
  enabled = true,
  filters: DashboardFilters | null = null,
) {
  const api = useApi();
  const view = filters ? JSON.stringify(filters) : undefined;
  return useQuery({
    queryKey: [...dashboardKeys.data, 'widget', widgetId, version, view ?? null] as const,
    enabled,
    placeholderData: keepPreviousData,
    refetchInterval: DATA_REFRESH_MS,
    queryFn: async () =>
      (
        await api.GET('/api/v1/dashboards/widgets/{widget_id}/data', {
          params: { path: { widget_id: widgetId }, query: view ? { filters: view } : {} },
        })
      ).data!,
  });
}

/** An unsaved spec's numbers: the starter layout, the add-chart preview, a template preview. */
export function useSpecData(
  kind: WidgetKind,
  spec: AnySpec,
  projectId: string | null,
  enabled = true,
  filters: DashboardFilters | null = null,
) {
  const api = useApi();
  return useQuery({
    queryKey: [...dashboardKeys.data, 'spec', kind, spec, projectId, filters] as const,
    enabled,
    retry: false,
    placeholderData: keepPreviousData,
    refetchInterval: DATA_REFRESH_MS,
    queryFn: async () =>
      (
        await api.POST('/api/v1/dashboards/query', {
          body: { kind, query_spec: spec, project_id: projectId, filters },
        })
      ).data!,
  });
}

export interface DrillPoint {
  spec: AnySpec;
  projectId: string | null;
  key?: string | null;
  bucketStart?: string | null;
  /** a stacked bar's segment */
  splitKey?: string | null;
  filters?: DashboardFilters | null;
}

/** The tasks behind one mark, listed with the same clause that counted them. */
export function useDrill(point: DrillPoint | null) {
  const api = useApi();
  return useQuery({
    queryKey: [...dashboardKeys.data, 'drill', point] as const,
    enabled: point !== null,
    queryFn: async () =>
      (
        await api.POST('/api/v1/dashboards/drill', {
          body: {
            query_spec: point!.spec,
            project_id: point!.projectId,
            key: point!.key ?? null,
            bucket_start: point!.bucketStart ?? null,
            split_key: point!.splitKey ?? null,
            filters: point!.filters ?? null,
            limit: 200,
          },
        })
      ).data!,
  });
}

export function useCreateDashboard() {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  return useMutation({
    mutationFn: async (body: {
      name: string;
      project_id?: string | null;
      portfolio_id?: string | null;
      starter?: boolean;
      quiet?: boolean;
    }) => {
      const { starter = true, name, project_id, portfolio_id } = body;
      return (await api.POST('/api/v1/dashboards', { body: { name, project_id, portfolio_id, starter } }))
        .data!;
    },
    onSuccess: (res, body) => {
      if (!body.quiet)
        undoToast(
          'Dashboard created',
          res.meta,
          () => void qc.invalidateQueries({ queryKey: dashboardKeys.all }),
        );
      qc.setQueryData(dashboardKeys.detail(res.data.id), res.data);
      void qc.invalidateQueries({ queryKey: dashboardKeys.list });
      if (res.data.project_id)
        void qc.invalidateQueries({ queryKey: dashboardKeys.project(res.data.project_id) });
      if (res.data.portfolio_id)
        void qc.invalidateQueries({ queryKey: dashboardKeys.portfolio(res.data.portfolio_id) });
    },
    onError: (e) => toastError(e, "Couldn't create the dashboard"),
  });
}

// ---------- Phase 7.5: pins, templates, the portfolio tab ----------

export function usePinnedDashboards(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: dashboardKeys.pinned,
    enabled,
    queryFn: async () => (await api.GET('/api/v1/dashboards/pinned')).data!.data,
  });
}

/** Pin to (or take off) my Home: personal, so no undo toast (like a favourite). */
export function usePin(dashboardId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (pinned: boolean) => {
      const params = { params: { path: { dashboard_id: dashboardId } } };
      return pinned
        ? (await api.PUT('/api/v1/dashboards/{dashboard_id}/pin', params)).data!
        : (await api.DELETE('/api/v1/dashboards/{dashboard_id}/pin', params)).data!;
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: dashboardKeys.all }),
    onError: (e) => toastError(e, "Couldn't change the pin"),
  });
}

export function useDashboardTemplates() {
  const api = useApi();
  return useQuery({
    queryKey: dashboardKeys.templates,
    staleTime: Infinity,
    queryFn: async () => (await api.GET('/api/v1/dashboards/templates')).data!.data,
  });
}

/** A template bound to a portfolio: its widgets and the notes on what didn't bind. */
export function useTemplatePreview(template: string | null, portfolioId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: [...dashboardKeys.templates, 'preview', template, portfolioId] as const,
    enabled: !!template && !!portfolioId,
    retry: false,
    queryFn: async () =>
      (
        await api.POST('/api/v1/dashboards/from-template/preview', {
          body: { template: template!, portfolio_id: portfolioId!, portfolio_tab: false },
        })
      ).data!,
  });
}

export function useCreateFromTemplate() {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  return useMutation({
    mutationFn: async (body: {
      template: string;
      portfolio_id: string;
      name?: string | null;
      portfolio_tab?: boolean;
    }) =>
      (
        await api.POST('/api/v1/dashboards/from-template', {
          body: { ...body, portfolio_tab: body.portfolio_tab ?? false },
        })
      ).data!,
    onSuccess: (res) => {
      undoToast(
        'Dashboard created',
        res.meta,
        () => void qc.invalidateQueries({ queryKey: dashboardKeys.all }),
      );
      qc.setQueryData(dashboardKeys.detail(res.data.dashboard.id), res.data.dashboard);
      void qc.invalidateQueries({ queryKey: dashboardKeys.list });
      if (res.data.dashboard.portfolio_id)
        void qc.invalidateQueries({
          queryKey: dashboardKeys.portfolio(res.data.dashboard.portfolio_id),
        });
    },
    onError: (e) => toastError(e, "Couldn't create the dashboard"),
  });
}

export function usePortfolioDashboard(portfolioId: string) {
  const api = useApi();
  return useQuery({
    queryKey: dashboardKeys.portfolio(portfolioId),
    queryFn: async () =>
      (
        await api.GET('/api/v1/dashboards/portfolio/{portfolio_id}', {
          params: { path: { portfolio_id: portfolioId } },
        })
      ).data!,
  });
}

/** Edits to one dashboard and its widgets; each refreshes the layout and offers Undo. */
export function useDashboardMutations(id: string | null) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const refresh = () => void qc.invalidateQueries({ queryKey: dashboardKeys.all });
  const done = (message: string) => ({
    onSuccess: (res: { meta: Meta }) => {
      undoToast(message, res.meta, refresh);
      refresh();
    },
    onError: (e: unknown) => toastError(e, "Couldn't update the dashboard"),
  });
  const need = (x: string | null) => {
    if (!x) throw new Error('No dashboard yet');
    return x;
  };

  const rename = useMutation({
    mutationFn: async (body: {
      name?: string;
      description?: string | null;
      filters?: DashboardFilters | null;
    }) =>
      (
        await api.PATCH('/api/v1/dashboards/{dashboard_id}', {
          params: { path: { dashboard_id: need(id) } },
          body,
        })
      ).data!,
    ...done('Dashboard updated'),
  });
  const remove = useMutation({
    mutationFn: async (dashboardId?: string) =>
      (
        await api.DELETE('/api/v1/dashboards/{dashboard_id}', {
          params: { path: { dashboard_id: need(dashboardId ?? id) } },
        })
      ).data!,
    ...done('Dashboard deleted'),
  });
  const addWidget = useMutation({
    mutationFn: async ({ dashboardId, body }: { dashboardId?: string; body: WidgetIn }) =>
      (
        await api.POST('/api/v1/dashboards/{dashboard_id}/widgets', {
          params: { path: { dashboard_id: need(dashboardId ?? id) } },
          body,
        })
      ).data!,
    ...done('Chart added'),
  });
  const updateWidget = useMutation({
    mutationFn: async ({ widgetId, body }: { widgetId: string; body: Partial<WidgetIn> }) =>
      (
        await api.PATCH('/api/v1/dashboards/widgets/{widget_id}', {
          params: { path: { widget_id: widgetId } },
          body,
        })
      ).data!,
    ...done('Chart updated'),
  });
  const removeWidget = useMutation({
    mutationFn: async (widgetId: string) =>
      (
        await api.DELETE('/api/v1/dashboards/widgets/{widget_id}', {
          params: { path: { widget_id: widgetId } },
        })
      ).data!,
    ...done('Chart removed'),
  });
  const moveWidget = useMutation({
    mutationFn: async ({
      widgetId,
      before_id,
      after_id,
    }: {
      widgetId: string;
      before_id?: string | null;
      after_id?: string | null;
    }) =>
      (
        await api.POST('/api/v1/dashboards/widgets/{widget_id}/move', {
          params: { path: { widget_id: widgetId } },
          body: { before_id: before_id ?? null, after_id: after_id ?? null },
        })
      ).data!,
    ...done('Chart moved'),
  });
  return { rename, remove, addWidget, updateWidget, removeWidget, moveWidget };
}
