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
  byProject: (projectId: string) => ['templates', 'task', projectId] as const,
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

/** S4.3.2: a project's own task templates. */
export function useTaskTemplates(projectId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: templateKeys.byProject(projectId),
    enabled: enabled && !!projectId,
    queryFn: async () =>
      (
        await api.GET('/api/v1/templates', {
          params: { query: { kind: 'task', project_id: projectId } },
        })
      ).data!.data as unknown as TemplateOut[],
  });
}

export function useSaveTaskTemplate(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      name: string;
      title: string;
      description?: string | null;
      subtasks: string[];
      field_values: Record<string, unknown>;
    }) => (await api.POST('/api/v1/templates/from-task', { body: { ...body, project_id: projectId } })).data!,
    onError: (e) => toastError(e, "Couldn't save this task template"),
    onSuccess: () => void qc.invalidateQueries({ queryKey: templateKeys.byProject(projectId) }),
  });
}

export function useNewTaskFromTemplate(templateId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (body: {
      section_id?: string | null;
      title?: string | null;
      assignee_id?: string | null;
      due_on?: string | null;
    }) =>
      (
        await api.POST('/api/v1/templates/{template_id}/new-task', {
          params: { path: { template_id: templateId } },
          body,
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't create a task from this template"),
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

export function useDeleteTemplate(kind: 'project' | 'task' = 'project', projectId?: string) {
  const api = useApi();
  const qc = useQueryClient();
  const key = kind === 'task' && projectId ? templateKeys.byProject(projectId) : templateKeys.byKind(kind);
  return useMutation({
    mutationFn: async (id: string) =>
      await api.DELETE('/api/v1/templates/{template_id}', { params: { path: { template_id: id } } }),
    onError: (e) => toastError(e, "Couldn't delete the template"),
    onSuccess: () => void qc.invalidateQueries({ queryKey: key }),
  });
}

// ---------------- S4.3.3 template from description (AI) ----------------

export interface DraftTask {
  title: string;
  description?: string | null;
  priority?: 'urgent' | 'high' | 'medium' | 'low' | null;
  due_in_days?: number | null;
  role?: string | null;
  subtasks: string[];
}
export interface DraftSection {
  name: string;
  tasks: DraftTask[];
}
export interface TemplateDraft {
  name: string;
  description?: string | null;
  sections: DraftSection[];
}

export function useDraftTemplateFromBrief() {
  const api = useApi();
  return useMutation({
    mutationFn: async (brief: string) =>
      (await api.POST('/api/v1/ai/templates/from-brief', { body: { brief } })).data! as TemplateDraft,
  });
}

export function useSaveTemplateFromBrief() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; description?: string | null; draft: TemplateDraft }) =>
      (await api.POST('/api/v1/ai/templates/from-brief/save', { body })).data!,
    onError: (e) => toastError(e, "Couldn't save this template"),
    onSuccess: () => void qc.invalidateQueries({ queryKey: templateKeys.byKind('project') }),
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
