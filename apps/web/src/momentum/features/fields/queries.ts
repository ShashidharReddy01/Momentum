import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useRecordUndo, useUndoToast } from '@/lib/undo';
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
  valuesByTask: (taskId: string) => ['tasks', taskId, 'fields'] as const,
  valuesByProject: (projectId: string) => ['projects', projectId, 'field-values'] as const,
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
  const record = useRecordUndo();
  const undoToast = useUndoToast();
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
    onSuccess: (res) => undoToast(`${res.data.name} archived in every project`, res.meta),
    onError: (e) => toastError(e, "Couldn't archive the field"),
    onSettled: settle,
  });

  const detach = useMutation({
    mutationFn: async (id: string) =>
      (
        await api.DELETE('/api/v1/projects/{project_id}/fields/{field_id}', {
          params: { path: { project_id: projectId, field_id: id } },
        })
      ).data!,
    onSuccess: (res) => undoToast('Field removed from this project', res.meta),
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
    onSuccess: (res) => record('Reordered fields', res.meta),
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
    onSuccess: (res, v) => record(`${v.visible ? 'Showed' : 'Hid'} ${res.data.name}`, res.meta),
    onError: (e) => toastError(e, "Couldn't update the field"),
    onSettled: settle,
  });

  return { create, attach, update, archive, detach, move, setVisible };
}

export type FieldValue = components['schemas']['FieldValueOut'];
export type TaskFieldValue = components['schemas']['TaskFieldValueOut'];

/** A task's custom field values, keyed by field id. */
export function useTaskFieldValues(taskId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: fieldKeys.valuesByTask(taskId),
    enabled: enabled && !!taskId,
    queryFn: async () =>
      (await api.GET('/api/v1/tasks/{task_id}/fields', { params: { path: { task_id: taskId } } })).data!.data,
    select: (rows) => new Map(rows.map((r) => [r.field_id, r.value])),
  });
}

/** Every field value across a project's tasks, in one request — for list/board rows, which
 * would otherwise need one `useTaskFieldValues` round trip per visible row (the whole point of
 * this endpoint: see its backend doc comment on the 2,000-task performance AC). Keyed by task
 * id, then field id. */
export function useProjectFieldValues(projectId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: fieldKeys.valuesByProject(projectId),
    enabled: enabled && !!projectId,
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/field-values', {
          params: { path: { project_id: projectId } },
        })
      ).data!.data,
    select: (rows) => {
      const byTask = new Map<string, Map<string, unknown>>();
      for (const r of rows) {
        let forTask = byTask.get(r.task_id);
        if (!forTask) byTask.set(r.task_id, (forTask = new Map()));
        forTask.set(r.field_id, r.value);
      }
      return byTask;
    },
  });
}

/** Set (or clear, with `value: null`) one field's value on a task. Optimistic: the pane and any
 * list/board chip showing this value update immediately. */
export function useSetFieldValue(taskId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const key = fieldKeys.valuesByTask(taskId);
  return useMutation({
    mutationFn: async (v: { fieldId: string; value: unknown }) =>
      (
        await api.PUT('/api/v1/tasks/{task_id}/fields/{field_id}', {
          params: { path: { task_id: taskId, field_id: v.fieldId } },
          body: { value: v.value },
        })
      ).data!,
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: key });
      const prevRows = qc.getQueryData<FieldValue[]>(key);
      qc.setQueryData<FieldValue[]>(key, (old) => {
        const rest = (old ?? []).filter((r) => r.field_id !== v.fieldId);
        return v.value === null ? rest : [...rest, { field_id: v.fieldId, value: v.value }];
      });
      return { prevRows };
    },
    onError: (e, _v, ctx) => {
      toastError(e, "Couldn't update the field");
      if (ctx?.prevRows) qc.setQueryData(key, ctx.prevRows);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: key });
      // Don't rely on the realtime round trip alone to refresh any open list/board's bulk
      // query (`useProjectFieldValues`) — realtime is off in some environments/tests, and even
      // when it's on, the actor's own edit is exactly the kind of echo it suppresses, so *this*
      // tab needs its own path to pick the change up.
      void qc.invalidateQueries({
        predicate: (q) => q.queryKey[2] === 'field-values' || q.queryKey[0] === 'field-values',
      });
    },
  });
}

/** S7.4.1: field values for tasks from anywhere (My Tasks spans projects), by task then field. */
export function useFieldValuesLookup(taskIds: readonly string[], enabled = true) {
  const api = useApi();
  const ids = [...taskIds].sort().slice(0, 2000);
  return useQuery({
    queryKey: ['field-values', 'lookup', ids],
    enabled: enabled && ids.length > 0,
    queryFn: async () =>
      (await api.POST('/api/v1/field-values/lookup', { body: { task_ids: ids } })).data!.data,
    select: (rows) => {
      const byTask = new Map<string, Map<string, unknown>>();
      for (const r of rows) {
        let forTask = byTask.get(r.task_id);
        if (!forTask) byTask.set(r.task_id, (forTask = new Map()));
        forTask.set(r.field_id, r.value);
      }
      return byTask;
    },
  });
}

// ---------------- Phase 7.5: project fields (spec §5.1) ----------------

export type ProjectFieldValue = components['schemas']['ProjectFieldValueOut'];
export type ProjectFieldEvent = components['schemas']['ProjectFieldEventOut'];

export const projectFieldKeys = {
  defs: ['project-fields'] as const,
  values: (projectId: string) => ['projects', projectId, 'project-field-values'] as const,
  history: (projectId: string) => ['projects', projectId, 'project-field-history'] as const,
};

/** The workspace's project fields (Stage, Account owner, Contract value…). */
export function useProjectFieldDefs(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: projectFieldKeys.defs,
    enabled,
    queryFn: async () => (await api.GET('/api/v1/project-fields')).data!.data,
  });
}

/** One project's values for the project fields, keyed by field id. */
export function useProjectDetails(projectId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: projectFieldKeys.values(projectId),
    enabled: enabled && !!projectId,
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/project-field-values', {
          params: { path: { project_id: projectId } },
        })
      ).data!.data,
    select: (rows) => new Map(rows.map((r) => [r.field_id, r.value as unknown])),
  });
}

/** Set (or clear) a project field on a project. Undoable: the toast offers Undo. */
export function useSetProjectDetail(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const key = projectFieldKeys.values(projectId);
  return useMutation({
    mutationFn: async (v: { field: Field; value: unknown }) =>
      (
        await api.PUT('/api/v1/projects/{project_id}/project-field-values/{field_id}', {
          params: { path: { project_id: projectId, field_id: v.field.id } },
          body: { value: v.value },
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't save that"),
    onSuccess: (res, v) => {
      if (res.meta.activity_id)
        undoToast(`${v.field.name} ${v.value === null ? 'cleared' : 'updated'}`, res.meta, () => {
          void qc.invalidateQueries({ queryKey: key });
        });
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: key });
      void qc.invalidateQueries({ queryKey: projectFieldKeys.history(projectId) });
    },
  });
}

/** Create or change a project field definition (workspace-wide). */
export function useProjectFieldDefMutations() {
  const api = useApi();
  const qc = useQueryClient();
  const settle = () => {
    void qc.invalidateQueries({ queryKey: projectFieldKeys.defs });
    void qc.invalidateQueries({ queryKey: fieldKeys.library });
  };
  const create = useMutation({
    mutationFn: async (v: FieldCreate) => (await api.POST('/api/v1/project-fields', { body: v })).data!,
    onError: (e) => toastError(e, "Couldn't create the field"),
    onSettled: settle,
  });
  const patch = useMutation({
    mutationFn: async (v: { fieldId: string; patch: FieldPatch }) =>
      (
        await api.PATCH('/api/v1/project-fields/{field_id}', {
          params: { path: { field_id: v.fieldId } },
          body: v.patch,
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't save the field"),
    onSettled: settle,
  });
  return { create, patch };
}
