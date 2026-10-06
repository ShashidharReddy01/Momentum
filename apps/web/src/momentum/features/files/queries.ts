import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type ProjectFile = components['schemas']['ProjectFileOut'];
export type FileVersion = components['schemas']['AttachmentOut'];
export type FileKind = ProjectFile['kind'];

export interface FileFilters {
  q?: string;
  kind?: FileKind;
  where?: 'project' | 'tasks' | 'comments' | 'all';
  source?: 'upload' | 'generated' | 'agent' | 'import';
  uploaded_by?: string;
  sort?: 'newest' | 'name' | 'size';
}

export const fileKeys = {
  project: (projectId: string) => ['files', 'project', projectId] as const,
  list: (projectId: string, f: FileFilters) => ['files', 'project', projectId, f] as const,
  versions: (id: string) => ['files', 'versions', id] as const,
};

/** Phase 7.5: a project's file inventory (current versions; project, tasks at any depth,
 * comments), 50 per page. */
export function useProjectFiles(projectId: string, filters: FileFilters) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: fileKeys.list(projectId, filters),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await api.GET('/api/v1/projects/{project_id}/files', {
          params: {
            path: { project_id: projectId },
            query: {
              ...(filters.q ? { q: filters.q } : {}),
              ...(filters.kind ? { kind: filters.kind } : {}),
              ...(filters.where ? { where: filters.where } : {}),
              ...(filters.source ? { source: filters.source } : {}),
              ...(filters.uploaded_by ? { uploaded_by: filters.uploaded_by } : {}),
              ...(filters.sort ? { sort: filters.sort } : {}),
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        })
      ).data!,
    getNextPageParam: (last) => last.next_cursor ?? null,
    // a new search or filter keeps the old rows on screen until the answer arrives
    placeholderData: keepPreviousData,
  });
}

export function useFileVersions(id: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: fileKeys.versions(id ?? ''),
    enabled: !!id,
    queryFn: async () =>
      (
        await api.GET('/api/v1/attachments/{attachment_id}/versions', {
          params: { path: { attachment_id: id! } },
        })
      ).data!.data,
  });
}

/** Upload to the project, as a new file or (``replaceId``) the next version of one of its own
 * files; delete with an Undo toast. Multipart bodies need the same cast as task attachments. */
export function useFileMutations(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const refresh = () => void qc.invalidateQueries({ queryKey: ['files'] });

  const upload = useMutation({
    mutationFn: async ({ file, replaceId }: { file: File; replaceId?: string }) => {
      const body = new FormData();
      body.append('file', file);
      if (replaceId) body.append('replace_id', replaceId);
      return (
        await api.POST('/api/v1/projects/{project_id}/files', {
          params: { path: { project_id: projectId } },
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          body: body as any,
        })
      ).data!;
    },
    onSuccess: (res, { file, replaceId }) => {
      refresh();
      undoToast(replaceId ? `Uploaded a new version of ${file.name}` : `Uploaded ${file.name}`, res.meta);
    },
    onError: (e) => toastError(e, "Couldn't upload that file"),
  });

  /** A new version of a task's or comment's file goes through that owner's upload route. */
  const uploadVersion = useMutation({
    mutationFn: async ({ file, target }: { file: File; target: ProjectFile }) => {
      const body = new FormData();
      body.append('file', file);
      body.append('replace_id', target.id);
      const loc = target.location;
      if (loc.type === 'comment' && loc.comment_id) {
        return (
          await api.POST('/api/v1/comments/{comment_id}/attachments', {
            params: { path: { comment_id: loc.comment_id } },
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            body: body as any,
          })
        ).data!;
      }
      if (loc.type === 'task' && loc.task_id) {
        return (
          await api.POST('/api/v1/tasks/{task_id}/attachments', {
            params: { path: { task_id: loc.task_id } },
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            body: body as any,
          })
        ).data!;
      }
      return (
        await api.POST('/api/v1/projects/{project_id}/files', {
          params: { path: { project_id: projectId } },
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          body: body as any,
        })
      ).data!;
    },
    onSuccess: (res, { file }) => {
      refresh();
      undoToast(`Uploaded a new version of ${file.name}`, res.meta);
    },
    onError: (e) => toastError(e, "Couldn't upload that version"),
  });

  const remove = useMutation({
    mutationFn: async (f: ProjectFile) =>
      (
        await api.DELETE('/api/v1/attachments/{attachment_id}', {
          params: { path: { attachment_id: f.id } },
        })
      ).data!,
    onSuccess: (res, f) => {
      refresh();
      undoToast(`Deleted ${f.filename}`, res.meta);
    },
    onError: (e) => toastError(e, "Couldn't delete that file"),
  });

  return { upload, uploadVersion, remove };
}
