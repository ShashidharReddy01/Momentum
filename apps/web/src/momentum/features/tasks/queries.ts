import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useRef } from 'react';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useRecordUndo, useUndoToast } from '@/lib/undo';
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
  projects: (taskId: string) => ['tasks', taskId, 'projects'] as const,
  otherPlacements: (projectId: string) => ['projects', projectId, 'other-placements'] as const,
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
  // keep an open task pane in step with list edits
  qc.setQueryData<Task>(taskKeys.detail(id), (old) => (old ? { ...old, ...fn(old) } : old));
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

export interface MoveVars {
  ids: string[]; // display order
  sectionId: string;
  afterId: string | null;
  beforeId: string | null;
  message?: string;
}

export interface BulkVars {
  ids: string[];
  action: 'update' | 'complete' | 'uncomplete' | 'delete';
  patch?: TaskPatch;
  message: string;
}

/** Optimistically place `ids` (in order) in a section after/before an anchor (or at its end). */
export function reorder(
  list: Task[],
  v: Pick<MoveVars, 'ids' | 'sectionId' | 'afterId' | 'beforeId'>,
): Task[] {
  const moving = new Set(v.ids);
  const byId = new Map(list.map((t) => [t.id, t]));
  const block = v.ids.flatMap((id) => {
    const t = byId.get(id);
    return t ? [{ ...t, section_id: v.sectionId }] : [];
  });
  const rest = list.filter((t) => !moving.has(t.id));
  let at: number;
  if (v.afterId) at = rest.findIndex((t) => t.id === v.afterId) + 1;
  else if (v.beforeId) at = rest.findIndex((t) => t.id === v.beforeId);
  else {
    at = -1;
    rest.forEach((t, i) => {
      if (t.section_id === v.sectionId) at = i + 1;
    });
  }
  if (at < 0) at = rest.length; // empty section: its tasks are grouped by section id, any spot works
  return [...rest.slice(0, at), ...block, ...rest.slice(at)];
}

/**
 * Task mutations for one project list. Creation is queued so that rapid Enter presses create
 * tasks in order even before earlier ones have real ids (temp id → server id).
 */
export function useTaskMutations(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const record = useRecordUndo();
  const key = taskKeys.byProject(projectId);
  const pending = useRef(new Map<string, Promise<string>>());
  // Order-changing requests run one at a time so the server sees moves in the order made.
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const serial = <R>(fn: () => Promise<R>): Promise<R> => {
    const run = queue.current.then(fn, fn);
    queue.current = run.catch(() => undefined);
    return run;
  };
  // Tasks with an order change still in flight: a response only lands when it is the latest.
  const inflight = useRef(new Map<string, number>());
  const track = (ids: string[], delta: 1 | -1) => {
    for (const id of ids) {
      const n = (inflight.current.get(id) ?? 0) + delta;
      if (n > 0) inflight.current.set(id, n);
      else inflight.current.delete(id);
    }
  };
  const refetchAll = () => qc.invalidateQueries({ queryKey: ['projects', projectId, 'tasks'] });
  const resolveId = async (id: string | null | undefined) =>
    id && isTemp(id) ? ((await pending.current.get(id)) ?? null) : (id ?? null);

  const create = (
    v: { title: string; sectionId: string; afterId: string | null },
    onCreated?: (realId: string) => void,
  ): string => {
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
      subtask_count: 0,
      completed_subtask_count: 0,
    };
    qc.setQueryData<Task[]>(key, (old) => insertAfter(old ?? [], optimistic, v.afterId));
    const promise = (async () => {
      const afterId = await resolveId(v.afterId);
      const res = await api.POST('/api/v1/projects/{project_id}/tasks', {
        params: { path: { project_id: projectId } },
        body: { title: v.title, section_id: v.sectionId, after_id: afterId },
      });
      const real = res.data!.data;
      record('Task created', res.data!.meta);
      qc.setQueryData<Task[]>(key, (old) => old?.map((t) => (t.id === id ? real : t)));
      onCreated?.(real.id);
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
    onSuccess: (res) => record('Task renamed', res.meta),
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
      else record('Task updated', res.meta);
    },
    onError: (e) => {
      toastError(e, "Couldn't update the task");
      void qc.invalidateQueries({ queryKey: key });
    },
  });

  /**
   * Move tasks (display order) to a slot: optimistic reorder in the cache, then one request
   * (single move → /move, several → /bulk as one undo batch).
   */
  const move = useMutation({
    mutationFn: (v: MoveVars) =>
      serial(async () => {
        const ids = await Promise.all(v.ids.map((id) => resolveId(id)));
        const body = {
          section_id: v.sectionId,
          after_id: await resolveId(v.afterId),
          before_id: await resolveId(v.beforeId),
        };
        if (ids.length === 1) {
          const res = (
            await api.POST('/api/v1/tasks/{task_id}/move', { params: { path: { task_id: ids[0]! } }, body })
          ).data!;
          return { tasks: [res.data], meta: res.meta };
        }
        const res = (
          await api.POST('/api/v1/tasks/bulk', {
            body: { task_ids: ids as string[], action: 'move', ...body },
          })
        ).data!;
        return { tasks: res.data.data, meta: res.meta };
      }),
    onMutate: async (v) => {
      track(v.ids, 1);
      await qc.cancelQueries({ queryKey: key });
      qc.setQueryData<Task[]>(key, (old) => (old ? reorder(old, v) : old));
    },
    onSettled: (_res, _e, v) => track(v.ids, -1),
    onSuccess: (res, v) => {
      const latest = res.tasks.filter((t) => (inflight.current.get(t.id) ?? 0) <= 1);
      const byId = new Map(latest.map((t) => [t.id, t]));
      qc.setQueryData<Task[]>(key, (old) => old?.map((t) => byId.get(t.id) ?? t));
      if (v.message) undoToast(v.message, res.meta, refetchAll);
      else record('Task moved', res.meta, refetchAll);
      // completed tasks have their own list; its order is refreshed lazily
      void qc.invalidateQueries({ queryKey: taskKeys.byProject(projectId, true), refetchType: 'none' });
    },
    onError: (e) => {
      toastError(e, "Couldn't move the task");
      void refetchAll();
    },
  });

  /** One action on several tasks (all-or-nothing on the server, one undo). */
  const bulk = useMutation({
    mutationFn: (v: BulkVars) =>
      serial(async () => {
        const ids = (await Promise.all(v.ids.map((id) => resolveId(id)))) as string[];
        return (
          await api.POST('/api/v1/tasks/bulk', { body: { task_ids: ids, action: v.action, patch: v.patch } })
        ).data!;
      }),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: ['projects', projectId, 'tasks'] });
      const ids = new Set(v.ids);
      const now = new Date().toISOString();
      for (const completed of [false, true]) {
        qc.setQueryData<Task[]>(taskKeys.byProject(projectId, completed), (old) => {
          if (!old) return old;
          if (v.action === 'delete') return old.filter((t) => !ids.has(t.id));
          return old.map((t) => {
            if (!ids.has(t.id)) return t;
            if (v.action === 'complete') return { ...t, completed_at: t.completed_at ?? now };
            if (v.action === 'uncomplete') return { ...t, completed_at: null };
            return { ...t, ...v.patch };
          });
        });
      }
    },
    onSuccess: (res, v) => {
      if (v.action !== 'delete') {
        const byId = new Map(res.data.data.map((t) => [t.id, t]));
        for (const completed of [false, true])
          qc.setQueryData<Task[]>(taskKeys.byProject(projectId, completed), (old) =>
            old?.map((t) => byId.get(t.id) ?? t),
          );
      }
      undoToast(v.message, res.meta, refetchAll);
      if (v.action === 'complete' || v.action === 'uncomplete') void refetchAll();
    },
    onError: (e) => {
      toastError(e, "Couldn't update the tasks");
      void refetchAll();
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

  return { create, createMany, rename, update, move, bulk, setCompleted, remove };
}

export type TaskProjectPlacement = components['schemas']['TaskProjectOut'];
export type OtherPlacement = components['schemas']['OtherPlacementOut'];

// Local duplicate of `detail.ts`'s `isTaskList` (same reason `subtasks.ts` has its own): a
// same-directory import cycle between the two modules is avoidable by not creating one.
const isTaskListKey = (key: readonly unknown[]) =>
  (key[0] === 'projects' || key[0] === 'tags') && key[2] === 'tasks';

/** Every project a task is placed in (S2.4.1 multi-homing) — for the pane's "Projects" row. */
export function useTaskProjects(taskId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: taskKeys.projects(taskId),
    enabled: enabled && !!taskId,
    queryFn: async () =>
      (await api.GET('/api/v1/tasks/{task_id}/projects', { params: { path: { task_id: taskId } } })).data!
        .data,
  });
}

/** For a project's own task list: every *other* project each visible task is also placed in, in
 * one request — mirrors `useProjectFieldValues`/`useProjectTaskTags` so the virtualized list
 * still pays one round trip, not one per row. Keyed by task id. */
export function useOtherPlacements(projectId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: taskKeys.otherPlacements(projectId),
    enabled: enabled && !!projectId,
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/other-placements', {
          params: { path: { project_id: projectId } },
        })
      ).data!.data,
    select: (rows) => {
      const byTask = new Map<string, OtherPlacement['project'][]>();
      for (const r of rows) {
        const list = byTask.get(r.task_id);
        if (list) list.push(r.project);
        else byTask.set(r.task_id, [r.project]);
      }
      return byTask;
    },
  });
}

/** Add/remove a task's project placements. Invalidates the task's own placement list, any
 * mounted project-level bulk "other placements" query (this task's old and new project, plus any
 * other project whose bulk query happens to include it — cheap and simple beats precise here),
 * and both projects' task lists so the row appears/disappears where it should. */
export function useTaskProjectMutations(taskId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const settle = () => {
    void qc.invalidateQueries({ queryKey: taskKeys.projects(taskId) });
    void qc.invalidateQueries({ predicate: (q) => isTaskListKey(q.queryKey) });
    void qc.invalidateQueries({ predicate: (q) => q.queryKey[2] === 'other-placements' });
  };

  const add = useMutation({
    mutationFn: async (v: {
      projectId: string;
      sectionId?: string | null;
      afterId?: string | null;
      beforeId?: string | null;
    }) =>
      (
        await api.POST('/api/v1/tasks/{task_id}/projects', {
          params: { path: { task_id: taskId } },
          body: {
            project_id: v.projectId,
            section_id: v.sectionId ?? null,
            after_id: v.afterId ?? null,
            before_id: v.beforeId ?? null,
          },
        })
      ).data!,
    onSuccess: (res) => undoToast(`Added to ${res.data.project.name}`, res.meta, settle),
    onError: (e) => toastError(e, "Couldn't add this task to that project"),
    onSettled: settle,
  });

  const remove = useMutation({
    mutationFn: async (projectId: string) =>
      (
        await api.DELETE('/api/v1/tasks/{task_id}/projects/{project_id}', {
          params: { path: { task_id: taskId, project_id: projectId } },
        })
      ).data!,
    onSuccess: (res) => undoToast('Removed from project', res.meta, settle),
    onError: (e) => toastError(e, "Couldn't remove this task from that project"),
    onSettled: settle,
  });

  return { add, remove };
}
