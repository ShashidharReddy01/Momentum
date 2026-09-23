import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { JSONContent } from '@tiptap/react';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import { taskKeys } from './queries';

export type Comment = components['schemas']['CommentOut'];
export const REACTIONS = ['👍', '❤️', '🎉', '😄', '👀', '🙏', '✅', '🚀'] as const;
export const commentKey = (taskId: string) => ['tasks', taskId, 'comments'] as const;

export function useComments(taskId: string) {
  const api = useApi();
  return useQuery({
    queryKey: commentKey(taskId),
    queryFn: async () =>
      (await api.GET('/api/v1/tasks/{task_id}/comments', { params: { path: { task_id: taskId } } })).data!
        .data,
  });
}

export function useCommentMutations(taskId: string, meId?: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const key = commentKey(taskId);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: key });
    void qc.invalidateQueries({ queryKey: taskKeys.detail(taskId) }); // followers may change
  };
  const replace = (c: Comment) =>
    qc.setQueryData<Comment[]>(key, (old) => old?.map((x) => (x.id === c.id ? c : x)));

  const create = useMutation({
    mutationFn: async (body: JSONContent) =>
      (
        await api.POST('/api/v1/tasks/{task_id}/comments', {
          params: { path: { task_id: taskId } },
          body: { body: body as Comment['body'] },
        })
      ).data!,
    onSuccess: (res) => {
      qc.setQueryData<Comment[]>(key, (old) => [...(old ?? []), res.data]);
      void qc.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
    },
    // the composer keeps the text (and its draft) when this fails
    onError: (e) => toastError(e, "Couldn't post the comment. Your text is kept."),
  });

  const edit = useMutation({
    mutationFn: async (v: { id: string; body: JSONContent }) =>
      (
        await api.PATCH('/api/v1/comments/{comment_id}', {
          params: { path: { comment_id: v.id } },
          body: { body: v.body as Comment['body'] },
        })
      ).data!,
    onSuccess: (res) => {
      replace(res.data);
      undoToast('Comment edited', res.meta, refresh);
    },
    onError: (e) => toastError(e, "Couldn't save the comment. Your text is kept."),
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      (await api.DELETE('/api/v1/comments/{comment_id}', { params: { path: { comment_id: id } } })).data!,
    onMutate: (id) => qc.setQueryData<Comment[]>(key, (old) => old?.filter((c) => c.id !== id)),
    onSuccess: (res) => undoToast('Comment deleted', res.meta, refresh),
    onError: (e) => {
      toastError(e);
      refresh();
    },
  });

  const react = useMutation({
    mutationFn: async (v: { id: string; emoji: string; active: boolean }) =>
      (
        await api.POST('/api/v1/comments/{comment_id}/reactions', {
          params: { path: { comment_id: v.id } },
          body: { emoji: v.emoji, active: v.active },
        })
      ).data!,
    onMutate: (v) =>
      qc.setQueryData<Comment[]>(key, (old) =>
        old?.map((c) => {
          if (c.id !== v.id || !meId) return c;
          const list = c.reactions.map((r) => ({ ...r, user_ids: r.user_ids.filter((u) => u !== meId) }));
          const hit = list.find((r) => r.emoji === v.emoji);
          if (v.active) {
            if (hit) hit.user_ids.push(meId);
            else list.push({ emoji: v.emoji, user_ids: [meId] });
          }
          // keep other emojis of mine that weren't touched
          const mine = c.reactions
            .filter((r) => r.emoji !== v.emoji && r.user_ids.includes(meId))
            .map((r) => r.emoji);
          return {
            ...c,
            reactions: list
              .map((r) => (mine.includes(r.emoji) ? { ...r, user_ids: [...r.user_ids, meId] } : r))
              .filter((r) => r.user_ids.length),
          };
        }),
      ),
    onSuccess: (res) => replace(res.data),
    onError: (e) => {
      toastError(e);
      refresh();
    },
  });

  return { create, edit, remove, react };
}
