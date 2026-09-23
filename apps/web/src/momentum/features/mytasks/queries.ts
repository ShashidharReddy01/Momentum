import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef } from 'react';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useRecordUndo, useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import { dropTask, syncTask, type TaskPatch } from '@/features/tasks';

export type MyTask = components['schemas']['MyTaskOut'];
export type Bucket = NonNullable<MyTask['bucket']>;
export const BUCKETS: { id: Bucket; name: string }[] = [
  { id: 'recently_assigned', name: 'Recently assigned' },
  { id: 'today', name: 'Today' },
  { id: 'this_week', name: 'This week' },
  { id: 'later', name: 'Later' },
];
export const myTasksKey = (completed: boolean) => ['me', 'tasks', { completed }] as const;

export function useMyTasks(completed = false, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: myTasksKey(completed),
    enabled,
    queryFn: async () => (await api.GET('/api/v1/me/tasks', { params: { query: { completed } } })).data!.data,
  });
}

/** Moves (serialized, optimistic) and task edits for My Tasks, kept in step with other views. */
export function useMyTaskMutations() {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const record = useRecordUndo();
  const key = myTasksKey(false);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const serial = <R>(fn: () => Promise<R>) => {
    const run = queue.current.then(fn, fn);
    queue.current = run.catch(() => undefined);
    return run;
  };
  const refresh = () => void qc.invalidateQueries({ queryKey: ['me', 'tasks'] });
  const patchLocal = (id: string, fields: Partial<MyTask>) => {
    for (const completed of [false, true])
      qc.setQueryData<MyTask[]>(myTasksKey(completed), (old) =>
        old?.map((t) => (t.id === id ? { ...t, ...fields } : t)),
      );
    syncTask(qc, id, fields);
  };

  const move = useMutation({
    mutationFn: (v: {
      id: string;
      bucket: Bucket;
      afterId: string | null;
      beforeId: string | null;
      message?: string;
    }) =>
      serial(
        async () =>
          (
            await api.POST('/api/v1/me/tasks/{task_id}/move', {
              params: { path: { task_id: v.id } },
              body: { bucket: v.bucket, after_id: v.afterId, before_id: v.beforeId },
            })
          ).data!,
      ),
    onMutate: (v) =>
      qc.setQueryData<MyTask[]>(key, (old) => {
        if (!old) return old;
        const moving = old.find((t) => t.id === v.id);
        if (!moving) return old;
        const rest = old.filter((t) => t.id !== v.id);
        let at: number;
        if (v.afterId) at = rest.findIndex((t) => t.id === v.afterId) + 1;
        else if (v.beforeId) at = rest.findIndex((t) => t.id === v.beforeId);
        else {
          at = -1;
          rest.forEach((t, i) => {
            if (t.bucket === v.bucket) at = i + 1;
          });
          if (at < 0) at = rest.length;
        }
        return [
          ...rest.slice(0, Math.max(0, at)),
          { ...moving, bucket: v.bucket },
          ...rest.slice(Math.max(0, at)),
        ];
      }),
    onSuccess: (res, v) =>
      v.message ? undoToast(v.message, res.meta, refresh) : record('Moved in My Tasks', res.meta, refresh),
    onError: (e) => {
      toastError(e, "Couldn't move the task");
      refresh();
    },
  });

  const update = useMutation({
    mutationFn: async (v: { id: string; patch: TaskPatch & { title?: string }; message?: string }) =>
      (await api.PATCH('/api/v1/tasks/{task_id}', { params: { path: { task_id: v.id } }, body: v.patch }))
        .data!,
    onMutate: (v) => patchLocal(v.id, v.patch as Partial<MyTask>),
    onSuccess: (res, v) => {
      patchLocal(v.id, res.data);
      if (v.message) undoToast(v.message, res.meta, refresh);
      else record('Task updated', res.meta, refresh);
      // assigned to someone else: it leaves My Tasks on the next load
      if ('assignee_id' in v.patch) refresh();
    },
    onError: (e) => {
      toastError(e, "Couldn't update the task");
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
    onMutate: (v) => patchLocal(v.id, { completed_at: v.completed ? new Date().toISOString() : null }),
    onSuccess: (res, v) => {
      if (v.completed) undoToast('Task completed', res.meta, refresh);
      void qc.invalidateQueries({ queryKey: myTasksKey(true) });
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
      qc.setQueryData<MyTask[]>(key, (old) => old?.filter((t) => t.id !== id));
      dropTask(qc, id);
    },
    onSuccess: (res) => undoToast('Task deleted', res.meta, refresh),
    onError: (e) => {
      toastError(e);
      refresh();
    },
  });

  return { move, update, setCompleted, remove };
}
