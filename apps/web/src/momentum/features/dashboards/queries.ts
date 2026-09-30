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
export type QuerySpec = components['schemas']['QuerySpec'];
export type QueryResult = components['schemas']['QueryResultOut'];
export type GroupRow = components['schemas']['GroupOut'];
export type SeriesPoint = components['schemas']['PointOut'];
export type TaskRow = components['schemas']['TaskRowOut'];
export type Drill = components['schemas']['DrillOut'];
type Meta = components['schemas']['MutationMeta'];

export const dashboardKeys = {
  all: ['dashboards'] as const,
  list: ['dashboards', 'list'] as const,
  detail: (id: string) => ['dashboards', id] as const,
  project: (projectId: string) => ['dashboards', 'project', projectId] as const,
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

/** A saved widget's numbers (as the viewer); `version` refetches after an edit. */
export function useWidgetData(widgetId: string, version: number, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: [...dashboardKeys.data, 'widget', widgetId, version] as const,
    enabled,
    placeholderData: keepPreviousData,
    refetchInterval: DATA_REFRESH_MS,
    queryFn: async () =>
      (
        await api.GET('/api/v1/dashboards/widgets/{widget_id}/data', {
          params: { path: { widget_id: widgetId } },
        })
      ).data!,
  });
}

/** An unsaved spec's numbers: the starter layout and the add-chart preview. */
export function useSpecData(kind: WidgetKind, spec: QuerySpec, projectId: string | null, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: [...dashboardKeys.data, 'spec', kind, spec, projectId] as const,
    enabled,
    retry: false,
    placeholderData: keepPreviousData,
    refetchInterval: DATA_REFRESH_MS,
    queryFn: async () =>
      (
        await api.POST('/api/v1/dashboards/query', {
          body: { kind, query_spec: spec, project_id: projectId },
        })
      ).data!,
  });
}

export interface DrillPoint {
  spec: QuerySpec;
  projectId: string | null;
  key?: string | null;
  bucketStart?: string | null;
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
      starter?: boolean;
      quiet?: boolean;
    }) => {
      const { starter = true, name, project_id } = body;
      return (await api.POST('/api/v1/dashboards', { body: { name, project_id, starter } })).data!;
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
    },
    onError: (e) => toastError(e, "Couldn't create the dashboard"),
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
    mutationFn: async (body: { name?: string; description?: string | null }) =>
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
