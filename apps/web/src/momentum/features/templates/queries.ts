import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export interface Role {
  id: string;
  label: string;
}

export type TemplateOut = Omit<components['schemas']['TemplateOut'], 'payload'> & {
  payload: { roles: Role[]; fields: string[]; sections: unknown[]; rules: unknown[] };
};

export const templateKeys = {
  byKind: (kind: 'project' | 'task') => ['templates', kind] as const,
};

export function useTemplates(kind: 'project' | 'task', enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: templateKeys.byKind(kind),
    enabled,
    queryFn: async () =>
      (await api.GET('/api/v1/templates', { params: { query: { kind } } })).data!
        .data as unknown as TemplateOut[],
  });
}

export function useSaveProjectTemplate() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { project_id: string; name: string; description?: string | null }) =>
      (await api.POST('/api/v1/templates/from-project', { body })).data!,
    onError: (e) => toastError(e, "Couldn't save this project as a template"),
    onSuccess: () => void qc.invalidateQueries({ queryKey: templateKeys.byKind('project') }),
  });
}

export function useDeleteTemplate(kind: 'project' | 'task' = 'project') {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      await api.DELETE('/api/v1/templates/{template_id}', { params: { path: { template_id: id } } }),
    onError: (e) => toastError(e, "Couldn't delete the template"),
    onSuccess: () => void qc.invalidateQueries({ queryKey: templateKeys.byKind(kind) }),
  });
}

export interface RoleMapping {
  role_id: string;
  user_id: string | null;
}

export function useNewProjectFromTemplate(templateId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (body: {
      team_id: string;
      name: string;
      start_date: string;
      privacy: 'team' | 'private';
      color?: string | null;
      role_mapping: RoleMapping[];
    }) =>
      (
        await api.POST('/api/v1/templates/{template_id}/new-project', {
          params: { path: { template_id: templateId } },
          body,
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't create a project from this template"),
  });
}
