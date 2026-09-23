import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useRef } from 'react';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type Task = components['schemas']['TaskOut'];
/** Field edits from the list (title has its own `rename`). */
export type TaskPatch = Pick<
  components['schemas']['TaskPatchIn'],
  'assignee_id' | 'start_on' | 'due_on' | 'due_at'
>;

export const taskKeys = {
  all: ['tasks'] as const,
  byProject: (projectId: string, completed = false) =>
    ['projects', projectId, 'tasks', { completed }] as const,
  detail: (id: string) => ['tasks', id] as const,
};

export const isTemp = (id: string) => id.startsWith('tmp-');
let tempSeq = 0;
const tempId = () => `tmp-${Date.now()}-${++tempSeq}`;

export function useProjectTasks(projectId: string, completed = false, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: taskKeys.byProject(projectId, completed),
    enabled,
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/tasks', {
          params: { path: { project_id: projectId }, query: { completed } },
        })
      ).data!.data,
  });
}

function patchTask(qc: QueryClient, projectId: string, id: string, fn: (t: Task) => Task) {
  for (const completed of [false, true]) {
    qc.setQueryData<Task[]>(taskKeys.byProject(projectId, completed), (old) =>
      old?.map((t) => (t.id === id ? fn(t) : t)),
    );
  }
}

function insertAfter(list: Task[], task: Task, afterId: string | null): Task[] {
  if (afterId) {
    const i = list.findIndex((t) => t.id === afterId);
    if (i >= 0) return [...list.slice(0, i + 1), task, ...list.slice(i + 1)];
  }
  // end of its section: after the last task of that section (list is grouped by section)
  let last = -1;
  list.forEach((t, i) => {
    if (t.section_id === task.section_id) last = i;
  });
  return last >= 0 ? [...list.slice(0, last + 1), task, ...list.slice(last + 1)] : [...list, task];
}

/**
 * Task mutations for one project list. Creation is queued so that rapid Enter presses create
 * tasks in order even before earlier ones have real ids (temp id → server id).
 */
export function useTaskMutations(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const key = taskKeys.byProject(projectId);
  const pending = useRef(new Map<string, Promise<string>>());
  const resolveId = async (id: string | null | undefined) =>
    id && isTemp(id) ? ((await pending.current.get(id)) ?? null) : (id ?? null);

  const create = (v: { title: string; sectionId: string; afterId: string | null }): string => {
    const id = tempId();
    const optimistic: Task = {
      id,
      number: 0,
      key: '',
      title: v.title,
      type: 'task',
      project_id: projectId,
      section_id: v.sectionId,
      position: null,
      assignee_id: null,
      start_on: null,
      due_on: null,
      due_at: null,
      completed_at: null,
      parent_id: null,
      priority: null,
      version: 1,
      created_at: new Date().toISOString(),
    };
    qc.setQueryData<Task[]>(key, (old) => insertAfter(old ?? [], optimistic, v.afterId));
    const promise = (async () => {
      const afterId = await resolveId(v.afterId);
      const res = await api.POST('/api/v1/projects/{project_id}/tasks', {
        params: { path: { project_id: projectId } },
        body: { title: v.title, section_id: v.sectionId, after_id: afterId },
      });
      const real = res.data!.data;
      qc.setQueryData<Task[]>(key, (old) => old?.map((t) => (t.id === id ? real : t)));
      return real.id;
    })();
    pending.current.set(id, promise);
    promise
      .catch((e) => {
        qc.setQueryData<Task[]>(key, (old) => old?.filter((t) => t.id !== id));
        toastError(e, "Couldn't create the task");
      })
      .finally(() => {
        // keep the mapping briefly so follow-up creates can still resolve it
        setTimeout(() => pending.current.delete(id), 30_000);
      });
    return id;
  };

  const createMany = useMutation({
    mutationFn: async (v: { titles: string[]; sectionId: string; afterId: string | null }) =>
      (
        await api.POST('/api/v1/projects/{project_id}/tasks/batch', {
          params: { path: { project_id: projectId } },
          body: { titles: v.titles, section_id: v.sectionId, after_id: await resolveId(v.afterId) },
        })
      ).data!,
    onSuccess: (res) => undoToast(`${res.data.data.length} tasks added`, res.meta),
    onError: (e) => toastError(e, "Couldn't add the tasks"),
    onSettled: () => qc.invalidateQueries({ queryKey: key }),
  });

  const rename = useMutation({
    mutationFn: async (v: { id: string; title: string }) =>
      (
        await api.PATCH('/api/v1/tasks/{task_id}', {
          params: { path: { task_id: (await resolveId(v.id))! } },
          body: { title: v.title },
        })
      ).data!,
    onMutate: (v) => patchTask(qc, projectId, v.id, (t) => ({ ...t, title: v.title })),
    onError: (e) => {
      toastError(e, "Couldn't rename the task");
      void qc.invalidateQueries({ queryKey: key });
    },
  });

  /** Assignee/date edits: optimistic, with an undo toast when `message` is given. */
  const update = useMutation({
    mutationFn: async (v: { id: string; patch: TaskPatch; message?: string }) =>
      (
        await api.PATCH('/api/v1/tasks/{task_id}', {
          params: { path: { task_id: (await resolveId(v.id))! } },
          body: v.patch,
        })
      ).data!,
    onMutate: (v) => patchTask(qc, projectId, v.id, (t) => ({ ...t, ...v.patch })),
    onSuccess: (res, v) => {
      patchTask(qc, projectId, v.id, () => res.data);
      if (v.message)
        undoToast(v.message, res.meta, () =>
          qc.invalidateQueries({ queryKey: ['projects', projectId, 'tasks'] }),
        );
    },
    onError: (e) => {
      toastError(e, "Couldn't update the task");
      void qc.invalidateQueries({ queryKey: key });
    },
  });

  const setCompleted = useMutation({
    mutationFn: async (v: { id: string; completed: boolean }) => {
      const path = { task_id: (await resolveId(v.id))! };
      return v.completed
        ? (await api.POST('/api/v1/tasks/{task_id}/complete', { params: { path } })).data!
        : (await api.POST('/api/v1/tasks/{task_id}/uncomplete', { params: { path } })).data!;
    },
    onMutate: (v) =>
      patchTask(qc, projectId, v.id, (t) => ({
        ...t,
        completed_at: v.completed ? new Date().toISOString() : null,
      })),
    onSuccess: (res, v) => {
      if (v.completed)
        undoToast('Task completed', res.meta, () =>
          qc.invalidateQueries({ queryKey: ['projects', projectId, 'tasks'] }),
        );
    },
    onError: (e) => {
      toastError(e);
      void qc.invalidateQueries({ queryKey: ['projects', projectId, 'tasks'] });
    },
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      (await api.DELETE('/api/v1/tasks/{task_id}', { params: { path: { task_id: (await resolveId(id))! } } }))
        .data!,
    onMutate: (id) => {
      for (const completed of [false, true]) {
        qc.setQueryData<Task[]>(taskKeys.byProject(projectId, completed), (old) =>
          old?.filter((t) => t.id !== id),
        );
      }
    },
    onSuccess: (res) => undoToast('Task deleted', res.meta),
    onError: (e) => {
      toastError(e);
      void qc.invalidateQueries({ queryKey: key });
    },
  });

  return { create, createMany, rename, update, setCompleted, remove };
}
