import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type Tag = components['schemas']['TagOut'];
export type TagCreate = components['schemas']['TagCreateIn'];
export type TagPatch = components['schemas']['TagPatchIn'];

export const tagKeys = {
  library: ['tags', 'library'] as const,
  byTask: (taskId: string) => ['tasks', taskId, 'tags'] as const,
  byProject: (projectId: string) => ['projects', projectId, 'task-tags'] as const,
  page: (tagId: string) => ['tags', tagId, 'tasks'] as const,
};

/** The workspace's tag library. */
export function useTagLibrary(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: tagKeys.library,
    enabled,
    queryFn: async () => (await api.GET('/api/v1/tags')).data!.data,
  });
}

/** Create/rename/recolor/delete tags in the workspace library. */
export function useTagMutations() {
  const api = useApi();
  const qc = useQueryClient();
  const settle = () => void qc.invalidateQueries({ queryKey: tagKeys.library });

  const create = useMutation({
    mutationFn: async (v: TagCreate) => (await api.POST('/api/v1/tags', { body: v })).data!,
    onError: (e) => toastError(e, "Couldn't create the tag"),
    onSettled: settle,
  });

  const update = useMutation({
    mutationFn: async (v: { id: string; patch: TagPatch }) =>
      (await api.PATCH('/api/v1/tags/{tag_id}', { params: { path: { tag_id: v.id } }, body: v.patch })).data!,
    onError: (e) => toastError(e, "Couldn't update the tag"),
    onSettled: settle,
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      await api.DELETE('/api/v1/tags/{tag_id}', { params: { path: { tag_id: id } } }),
    onError: (e) => toastError(e, "Couldn't delete the tag"),
    onSettled: settle,
  });

  return { create, update, remove };
}

export function useTaskTags(taskId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: tagKeys.byTask(taskId),
    enabled: enabled && !!taskId,
    queryFn: async () =>
      (await api.GET('/api/v1/tasks/{task_id}/tags', { params: { path: { task_id: taskId } } })).data!.data,
  });
}

/** Every tag across a project's tasks, in one request — for list/board rows, mirroring
 * `useProjectFieldValues` so a virtualized list still pays one round trip, not one per row.
 * Keyed by task id. */
export function useProjectTaskTags(projectId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: tagKeys.byProject(projectId),
    enabled: enabled && !!projectId,
    queryFn: async () =>
      (
        await api.GET('/api/v1/projects/{project_id}/task-tags', {
          params: { path: { project_id: projectId } },
        })
      ).data!.data,
    select: (rows) => {
      const byTask = new Map<string, Tag[]>();
      for (const r of rows) {
        const list = byTask.get(r.task_id);
        if (list) list.push(r.tag);
        else byTask.set(r.task_id, [r.tag]);
      }
      return byTask;
    },
  });
}

/** The tag page: tasks across every visible project carrying this tag. */
export function useTagTasks(tagId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: tagKeys.page(tagId),
    enabled: enabled && !!tagId,
    queryFn: async () =>
      (await api.GET('/api/v1/tags/{tag_id}/tasks', { params: { path: { tag_id: tagId } } })).data!.data,
  });
}

/** Attach (existing tag_id, or create-inline by name) / detach a tag on a task. Invalidates this
 * task's own tags and any mounted project-level bulk query — same "don't rely on the realtime
 * echo" reasoning as `useSetFieldValue`. */
export function useTaskTagMutations(taskId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const settle = () => {
    void qc.invalidateQueries({ queryKey: tagKeys.byTask(taskId) });
    void qc.invalidateQueries({ queryKey: tagKeys.library });
    void qc.invalidateQueries({ predicate: (q) => q.queryKey[2] === 'task-tags' });
  };

  const add = useMutation({
    mutationFn: async (v: { tagId?: string; name?: string }) =>
      (
        await api.POST('/api/v1/tasks/{task_id}/tags', {
          params: { path: { task_id: taskId } },
          body: { tag_id: v.tagId ?? null, name: v.name ?? null },
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't tag the task"),
    onSettled: settle,
  });

  const remove = useMutation({
    mutationFn: async (tagId: string) =>
      await api.DELETE('/api/v1/tasks/{task_id}/tags/{tag_id}', {
        params: { path: { task_id: taskId, tag_id: tagId } },
      }),
    onError: (e) => toastError(e, "Couldn't remove the tag"),
    onSettled: settle,
  });

  return { add, remove };
}
