import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef } from 'react';
import { toastError } from '@/lib/toast';
import { useRecordUndo, useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import { syncTask } from './detail';
import { taskKeys, type Task, type TaskPatch } from './queries';

export const subtaskKey = (parentId: string) => ['tasks', parentId, 'subtasks'] as const;
const isTaskList = (key: readonly unknown[]) => key[0] === 'projects' && key[2] === 'tasks';

export function useSubtasks(parentId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: subtaskKey(parentId),
    enabled,
    queryFn: async () =>
      (await api.GET('/api/v1/tasks/{task_id}/subtasks', { params: { path: { task_id: parentId } } })).data!
        .data,
  });
}

/**
 * Subtask mutations for one parent. Creates run one after another (Enter-chaining keeps order,
 * like the list), and every change keeps the parent's ↳ counts in step everywhere.
 */
export function useSubtaskMutations(parentId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const record = useRecordUndo();
  const key = subtaskKey(parentId);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const serial = <R>(fn: () => Promise<R>) => {
    const run = queue.current.then(fn, fn);
    queue.current = run.catch(() => undefined);
    return run;
  };
  const recount = () => {
    const list = qc.getQueryData<Task[]>(key) ?? [];
    syncTask(qc, parentId, {
      subtask_count: list.length,
      completed_subtask_count: list.filter((t) => t.completed_at).length,
    });
  };
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: key });
    void qc.invalidateQueries({ queryKey: taskKeys.detail(parentId) });
    void qc.invalidateQueries({ predicate: (q) => isTaskList(q.queryKey) });
  };
  const patchLocal = (id: string, fields: Partial<Task>) => {
    qc.setQueryData<Task[]>(key, (old) => old?.map((t) => (t.id === id ? { ...t, ...fields } : t)));
    syncTask(qc, id, fields);
  };

  const create = useMutation({
    // Appends at the end on the server. Requests are serialized, so rapid Enter presses land in
    // order; no client-side anchor (it could be stale while an earlier create is in flight).
    mutationFn: (v: { title: string }) =>
      serial(
        async () =>
          (
            await api.POST('/api/v1/tasks/{task_id}/subtasks', {
              params: { path: { task_id: parentId } },
              body: { title: v.title },
            })
          ).data!,
      ),
    onMutate: (v) => {
      const temp: Task = {
        id: `tmp-sub-${Date.now()}-${Math.random()}`,
        number: 0,
        key: '',
        title: v.title,
        type: 'task',
        project_id: null,
        section_id: null,
        position: null,
        assignee_id: null,
        start_on: null,
        due_on: null,
        due_at: null,
        completed_at: null,
        parent_id: parentId,
        priority: null,
        version: 1,
        created_at: new Date().toISOString(),
        subtask_count: 0,
        completed_subtask_count: 0,
      };
      qc.setQueryData<Task[]>(key, (old) => [...(old ?? []), temp]);
      recount();
      return { tempId: temp.id };
    },
    onSuccess: (res, _v, c) => {
      qc.setQueryData<Task[]>(key, (old) => old?.map((t) => (t.id === c?.tempId ? res.data : t)));
      recount();
      record('Subtask added', res.meta, refresh);
    },
    onError: (e, _v, c) => {
      qc.setQueryData<Task[]>(key, (old) => old?.filter((t) => t.id !== c?.tempId));
      recount();
      toastError(e, "Couldn't add the subtask");
    },
  });

  const update = useMutation({
    mutationFn: async (v: { id: string; patch: TaskPatch & { title?: string }; message?: string }) =>
      (await api.PATCH('/api/v1/tasks/{task_id}', { params: { path: { task_id: v.id } }, body: v.patch }))
        .data!,
    onMutate: (v) => patchLocal(v.id, v.patch as Partial<Task>),
    onSuccess: (res, v) => {
      patchLocal(v.id, res.data);
      if (v.message) undoToast(v.message, res.meta, refresh);
      else record('Subtask updated', res.meta, refresh);
    },
    onError: (e) => {
      toastError(e, "Couldn't update the subtask");
      refresh();
    },
  });

  const setCompleted = useMutation({
    mutationFn: async (v: { id: string; completed: boolean }) => {
      const params = { params: { path: { task_id: v.id } } };
      return v.completed
        ? (await api.POST('/api/v1/tasks/{task_id}/complete', params)).data!
        : (await api.POST('/api/v1/tasks/{task_id}/uncomplete', params)).data!;
    },
    onMutate: (v) => {
      patchLocal(v.id, { completed_at: v.completed ? new Date().toISOString() : null });
      recount();
    },
    onSuccess: (res, v) => {
      patchLocal(v.id, { completed_at: res.data.completed_at, version: res.data.version });
      if (v.completed) undoToast('Subtask completed', res.meta, refresh);
    },
    onError: (e) => {
      toastError(e);
      refresh();
    },
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      (await api.DELETE('/api/v1/tasks/{task_id}', { params: { path: { task_id: id } } })).data!,
    onMutate: (id) => {
      qc.setQueryData<Task[]>(key, (old) => old?.filter((t) => t.id !== id));
      recount();
    },
    onSuccess: (res) => undoToast('Subtask deleted', res.meta, refresh),
    onError: (e) => {
      toastError(e);
      refresh();
    },
  });

  const reorder = useMutation({
    mutationFn: (v: { id: string; afterId: string | null; beforeId: string | null }) =>
      serial(
        async () =>
          (
            await api.POST('/api/v1/tasks/{task_id}/subtask-move', {
              params: { path: { task_id: v.id } },
              body: v.afterId ? { after_id: v.afterId } : { before_id: v.beforeId },
            })
          ).data!,
      ),
    onMutate: (v) =>
      qc.setQueryData<Task[]>(key, (old) => {
        if (!old) return old;
        const moving = old.find((t) => t.id === v.id);
        if (!moving) return old;
        const rest = old.filter((t) => t.id !== v.id);
        const at = v.afterId
          ? rest.findIndex((t) => t.id === v.afterId) + 1
          : rest.findIndex((t) => t.id === v.beforeId);
        return [...rest.slice(0, Math.max(0, at)), moving, ...rest.slice(Math.max(0, at))];
      }),
    onSuccess: (res, v) => {
      qc.setQueryData<Task[]>(key, (old) => old?.map((t) => (t.id === v.id ? res.data : t)));
      record('Subtask moved', res.meta, refresh);
    },
    onError: (e) => {
      toastError(e, "Couldn't move the subtask");
      refresh();
    },
  });

  const outdent = useMutation({
    mutationFn: async (id: string) =>
      (await api.POST('/api/v1/tasks/{task_id}/outdent', { params: { path: { task_id: id } } })).data!,
    onMutate: (id) => {
      qc.setQueryData<Task[]>(key, (old) => old?.filter((t) => t.id !== id));
      recount();
    },
    onSuccess: (res) => {
      undoToast('Moved out of the parent task', res.meta, refresh);
      refresh();
    },
    onError: (e) => {
      toastError(e, "Couldn't move the subtask");
      refresh();
    },
  });

  return { create, update, setCompleted, remove, reorder, outdent };
}
