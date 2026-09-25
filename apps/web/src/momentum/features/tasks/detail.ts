import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useRecordUndo, useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import { completeWithConfirm, taskKeys, type Task, type TaskPatch } from './queries';

export type TaskDetail = components['schemas']['TaskDetailOut'];

export function useTaskDetail(taskId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: taskKeys.detail(taskId ?? ''),
    enabled: !!taskId,
    queryFn: async () =>
      (await api.GET('/api/v1/tasks/{task_id}', { params: { path: { task_id: taskId! } } })).data!,
  });
}

/** Any cached task-list query a single task's fields/completion should stay in sync with — a
 * project's list (`['projects', id, 'tasks']`) or a tag page (`['tags', id, 'tasks']`). */
export const isTaskList = (key: readonly unknown[]) =>
  (key[0] === 'projects' || key[0] === 'tags') && key[2] === 'tasks';

/**
 * Apply a task change everywhere it's cached (the open pane and any project list), so the list and
 * the pane never disagree. `fields` are merged; list rows only take the fields they have.
 */
export function syncTask(qc: QueryClient, id: string, fields: Partial<TaskDetail>) {
  qc.setQueryData<TaskDetail>(taskKeys.detail(id), (old) => (old ? { ...old, ...fields } : old));
  qc.setQueriesData<Task[]>({ predicate: (q) => isTaskList(q.queryKey) }, (old) => {
    if (!Array.isArray(old) || !old.some((t) => t.id === id)) return old;
    return old.map((t) => {
      if (t.id !== id) return t;
      const next = { ...t };
      for (const k of Object.keys(t) as (keyof Task)[]) {
        if (k in fields) (next as Record<string, unknown>)[k] = (fields as Record<string, unknown>)[k];
      }
      return next;
    });
  });
}

export function dropTask(qc: QueryClient, id: string) {
  qc.setQueriesData<Task[]>({ predicate: (q) => isTaskList(q.queryKey) }, (old) =>
    Array.isArray(old) ? old.filter((t) => t.id !== id) : old,
  );
}

/** Pane edits for one task (optimistic, synced to lists; description saves live in the editor). */
export function useTaskDetailMutations(taskId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const record = useRecordUndo();
  const refetch = () => {
    void qc.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
    void qc.invalidateQueries({ predicate: (q) => isTaskList(q.queryKey) });
  };

  const update = useMutation({
    mutationFn: async (v: { patch: TaskPatch & { title?: string }; message?: string }) =>
      (await api.PATCH('/api/v1/tasks/{task_id}', { params: { path: { task_id: taskId } }, body: v.patch }))
        .data!,
    onMutate: (v) => syncTask(qc, taskId, v.patch as Partial<TaskDetail>),
    onSuccess: (res, v) => {
      syncTask(qc, taskId, res.data);
      if (v.message) undoToast(v.message, res.meta, refetch);
      else record('Task updated', res.meta, refetch);
    },
    onError: (e) => {
      toastError(e, "Couldn't update the task");
      refetch();
    },
  });

  const setCompleted = useMutation({
    mutationFn: async (completed: boolean) => completeWithConfirm(api, taskId, completed),
    onMutate: (completed) =>
      syncTask(qc, taskId, { completed_at: completed ? new Date().toISOString() : null }),
    onSuccess: (res, completed) => {
      syncTask(qc, taskId, res.data);
      // move it between the open/completed lists on the next render
      void qc.invalidateQueries({ predicate: (q) => isTaskList(q.queryKey) });
      if (completed) undoToast('Task completed', res.meta, refetch);
    },
    onError: (e) => {
      toastError(e);
      refetch();
    },
  });

  const remove = useMutation({
    mutationFn: async () =>
      (await api.DELETE('/api/v1/tasks/{task_id}', { params: { path: { task_id: taskId } } })).data!,
    onMutate: () => dropTask(qc, taskId),
    onSuccess: (res) => undoToast('Task deleted', res.meta, refetch),
    onError: (e) => {
      toastError(e, "Couldn't delete the task");
      refetch();
    },
  });

  const convert = useMutation({
    mutationFn: async (type: 'task' | 'milestone') =>
      (
        await api.POST('/api/v1/tasks/{task_id}/convert', {
          params: { path: { task_id: taskId } },
          body: { type },
        })
      ).data!,
    onSuccess: (res, type) => {
      syncTask(qc, taskId, res.data);
      undoToast(type === 'milestone' ? 'Converted to milestone' : 'Converted to task', res.meta, refetch);
    },
    onError: (e) => {
      toastError(e, "Couldn't convert this task");
      refetch();
    },
  });

  return { update, setCompleted, remove, convert };
}
