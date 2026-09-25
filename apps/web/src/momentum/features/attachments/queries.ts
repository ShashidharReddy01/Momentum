import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type Attachment = components['schemas']['AttachmentOut'];

export const attachmentKeys = {
  forTask: (taskId: string) => ['attachments', 'task', taskId] as const,
};

export function useTaskAttachments(taskId: string) {
  const api = useApi();
  return useQuery({
    queryKey: attachmentKeys.forTask(taskId),
    queryFn: async () =>
      (
        await api.GET('/api/v1/tasks/{task_id}/attachments', {
          params: { path: { task_id: taskId } },
        })
      ).data!.data,
  });
}

/** Upload/delete for a task's files (S2.6.1). Upload is multipart, which openapi-typescript
 * types as a plain `string` field (a known codegen gap, same one S2.3.1's field-creation form
 * hit) — the cast below is the one place that works around it rather than fighting the type. */
export function useAttachmentMutations(taskId: string) {
  const api = useApi();
  const qc = useQueryClient();

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append('file', file);
      const res = await api.POST('/api/v1/tasks/{task_id}/attachments', {
        params: { path: { task_id: taskId } },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        body: body as any,
      });
      return res.data!;
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: attachmentKeys.forTask(taskId) }),
    onError: (e) => toastError(e, "Couldn't upload that file"),
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      (
        await api.DELETE('/api/v1/attachments/{attachment_id}', {
          params: { path: { attachment_id: id } },
        })
      ).data!,
    onMutate: (id) => {
      qc.setQueryData<Attachment[]>(attachmentKeys.forTask(taskId), (old) => old?.filter((a) => a.id !== id));
    },
    onError: (e) => toastError(e, "Couldn't remove that file"),
    onSettled: () => void qc.invalidateQueries({ queryKey: attachmentKeys.forTask(taskId) }),
  });

  return { upload, remove };
}
