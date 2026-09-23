import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { JSONContent } from '@tiptap/react';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';
import { taskKeys } from './queries';

export type Comment = components['schemas']['CommentOut'];
export type FeedItem = components['schemas']['FeedItemOut'];
export type ActivityItem = components['schemas']['ActivityItemOut'];
export const feedKey = (taskId: string) => ['tasks', taskId, 'feed'] as const;

/** Comments and activity for a task, oldest first. */
export function useTaskFeed(taskId: string) {
  const api = useApi();
  return useQuery({
    queryKey: feedKey(taskId),
    queryFn: async () =>
      (await api.GET('/api/v1/tasks/{task_id}/feed', { params: { path: { task_id: taskId } } })).data!,
  });
}
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
  const fkey = feedKey(taskId);
  type Feed = { data: FeedItem[]; truncated: boolean };
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: key });
    void qc.invalidateQueries({ queryKey: feedKey(taskId) });
    void qc.invalidateQueries({ queryKey: taskKeys.detail(taskId) }); // followers may change
  };
  const replace = (c: Comment) => {
    qc.setQueryData<Comment[]>(key, (old) => old?.map((x) => (x.id === c.id ? c : x)));
    qc.setQueryData<Feed>(fkey, (old) =>
      old ? { ...old, data: old.data.map((i) => (i.comment?.id === c.id ? { ...i, comment: c } : i)) } : old,
    );
  };

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
      qc.setQueryData<Feed>(fkey, (old) =>
        old
          ? { ...old, data: [...old.data, { kind: 'comment', at: res.data.created_at, comment: res.data }] }
          : old,
      );
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
    onMutate: (id) => {
      qc.setQueryData<Comment[]>(key, (old) => old?.filter((c) => c.id !== id));
      qc.setQueryData<Feed>(fkey, (old) =>
        old ? { ...old, data: old.data.filter((i) => i.comment?.id !== id) } : old,
      );
    },
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
    onMutate: (v) => {
      if (!meId) return;
      const apply = (c: Comment) => (c.id === v.id ? applyReaction(c, v.emoji, v.active, meId) : c);
      qc.setQueryData<Comment[]>(key, (old) => old?.map(apply));
      qc.setQueryData<Feed>(fkey, (old) =>
        old
          ? { ...old, data: old.data.map((i) => (i.comment ? { ...i, comment: apply(i.comment) } : i)) }
          : old,
      );
    },
    onSuccess: (res) => replace(res.data),
    onError: (e) => {
      toastError(e);
      refresh();
    },
  });

  return { create, edit, remove, react };
}

/** A comment with my reaction `emoji` turned on or off (other reactions untouched). */
export function applyReaction(c: Comment, emoji: string, active: boolean, me: string): Comment {
  const reactions = c.reactions.map((r) => ({ ...r, user_ids: [...r.user_ids] }));
  const hit = reactions.find((r) => r.emoji === emoji);
  if (active) {
    if (!hit) reactions.push({ emoji, user_ids: [me] });
    else if (!hit.user_ids.includes(me)) hit.user_ids.push(me);
  } else if (hit) {
    hit.user_ids = hit.user_ids.filter((u) => u !== me);
  }
  return { ...c, reactions: reactions.filter((r) => r.user_ids.length) };
}
