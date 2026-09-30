import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type Forecast = components['schemas']['ForecastOut'];

export const forecastKey = (projectId: string) => ['projects', projectId, 'forecast'] as const;

/** A project's latest forecast (S6.5.3), or null before the first one is computed. */
export function useForecast(projectId: string) {
  const api = useApi();
  return useQuery({
    queryKey: forecastKey(projectId),
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/forecast', {
          params: { path: { project_id: projectId } },
        })
      ).data!.forecast ?? null,
  });
}

export function useRefreshForecast(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (
        await api.POST('/api/v1/projects/{project_id}/forecast', {
          params: { path: { project_id: projectId } },
        })
      ).data!.forecast,
    onSuccess: (f) => qc.setQueryData(forecastKey(projectId), f),
    onError: (e) => toastError(e, "Couldn't update the forecast"),
  });
}
