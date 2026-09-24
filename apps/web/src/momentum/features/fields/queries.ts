import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type Field = components['schemas']['FieldOut'];
export type ProjectField = components['schemas']['ProjectFieldOut'];
export type FieldType = Field['type'];
export type SelectOption = components['schemas']['SelectOptionOut'];
export type FieldCreate = components['schemas']['FieldCreateIn'];
export type FieldPatch = components['schemas']['FieldPatchIn'];

export const fieldKeys = {
  library: ['fields', 'library'] as const,
  byProject: (projectId: string) => ['projects', projectId, 'fields'] as const,
};

/** The workspace's shared field library — fields any project can attach. */
export function useFieldLibrary(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: fieldKeys.library,
    enabled,
    queryFn: async () => (await api.GET('/api/v1/fields')).data!.data,
  });
}

export function useProjectFields(projectId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: fieldKeys.byProject(projectId),
    enabled: enabled && !!projectId,
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/fields', {
          params: { path: { project_id: projectId } },
        })
      ).data!.data,
  });
}

/** Field definitions and their attachment to this project. Not undoable (see the backend's own
 * doc comment on `domain/fields/service.py`): these are infrequent, deliberate settings changes,
 * not the fat-finger-prone kind of action undo mainly protects against. */
export function useFieldMutations(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const key = fieldKeys.byProject(projectId);
  const settle = () => {
    void qc.invalidateQueries({ queryKey: key });
    void qc.invalidateQueries({ queryKey: fieldKeys.library });
  };

  const create = useMutation({
    mutationFn: async (v: FieldCreate) =>
      (
        await api.POST('/api/v1/projects/{project_id}/fields', {
          params: { path: { project_id: projectId } },
          body: v,
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't add the field"),
    onSettled: settle,
  });

  const attach = useMutation({
    mutationFn: async (v: { fieldId: string; afterId?: string | null; beforeId?: string | null }) =>
      (
        await api.POST('/api/v1/projects/{project_id}/fields/attach', {
          params: { path: { project_id: projectId } },
          body: { field_id: v.fieldId, after_id: v.afterId ?? null, before_id: v.beforeId ?? null },
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't attach the field"),
    onSettled: settle,
  });

  const update = useMutation({
    mutationFn: async (v: { id: string; patch: FieldPatch }) =>
      (
        await api.PATCH('/api/v1/projects/{project_id}/fields/{field_id}', {
          params: { path: { project_id: projectId, field_id: v.id } },
          body: v.patch,
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't update the field"),
    onSettled: settle,
  });

  const archive = useMutation({
    mutationFn: async (id: string) =>
      (
        await api.POST('/api/v1/projects/{project_id}/fields/{field_id}/archive', {
          params: { path: { project_id: projectId, field_id: id } },
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't archive the field"),
    onSettled: settle,
  });

  const detach = useMutation({
    mutationFn: async (id: string) =>
      await api.DELETE('/api/v1/projects/{project_id}/fields/{field_id}', {
        params: { path: { project_id: projectId, field_id: id } },
      }),
    onError: (e) => toastError(e, "Couldn't remove the field"),
    onSettled: settle,
  });

  const move = useMutation({
    mutationFn: async (v: { id: string; afterId?: string | null; beforeId?: string | null }) =>
      (
        await api.POST('/api/v1/projects/{project_id}/fields/{field_id}/move', {
          params: { path: { project_id: projectId, field_id: v.id } },
          body: { after_id: v.afterId ?? null, before_id: v.beforeId ?? null },
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't reorder the fields"),
    onSettled: settle,
  });

  const setVisible = useMutation({
    mutationFn: async (v: { id: string; visible: boolean }) =>
      (
        await api.PATCH('/api/v1/projects/{project_id}/fields/{field_id}/visibility', {
          params: { path: { project_id: projectId, field_id: v.id } },
          body: { is_visible: v.visible },
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't update the field"),
    onSettled: settle,
  });

  return { create, attach, update, archive, detach, move, setVisible };
}
