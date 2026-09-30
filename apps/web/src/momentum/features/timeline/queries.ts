import { useQuery } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';

export type DependencyEdge = components['schemas']['DependencyEdgeOut'];

export const timelineKeys = {
  dependencies: (projectId: string) => ['projects', projectId, 'dependencies'] as const,
};

/** Every dependency between two tasks of the project, in one round trip (S6.1.1a). */
export function useProjectDependencies(projectId: string) {
  const api = useApi();
  return useQuery({
    queryKey: timelineKeys.dependencies(projectId),
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/dependencies', {
          params: { path: { project_id: projectId } },
        })
      ).data!.data,
  });
}
