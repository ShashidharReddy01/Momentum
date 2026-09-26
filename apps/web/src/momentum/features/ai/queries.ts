import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';
import type { components } from '@/lib/api/schema';
import { useMomentumConfig } from '@/lib/config';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';
import { errorText } from './errors';

export type AiAction = components['schemas']['AiActionOut'];
export type AiOperation = components['schemas']['AiOperationOut'];
export type DiffRow = components['schemas']['DiffRowOut'];
export type ApplyOutcome = components['schemas']['ApplyOut']['outcome'];

export const aiKeys = {
  action: (id: string) => ['ai', 'actions', id] as const,
};

/** One proposed AI action (S3.1.3). */
export function useAiAction(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: aiKeys.action(id),
    queryFn: async () =>
      (await api.GET('/api/v1/ai/actions/{action_id}', { params: { path: { action_id: id } } })).data!.data,
  });
}

/** Apply / dismiss / undo a proposed action. Every response carries the action's new state,
 * which replaces the cached one; applying or undoing also refreshes whatever it changed. */
export function useAiActionMutations(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  const path = { params: { path: { action_id: id } } };
  const put = (a: AiAction) => qc.setQueryData(aiKeys.action(id), a);

  const apply = useMutation({
    mutationFn: async (confirmHighRisk: boolean) =>
      (
        await api.POST('/api/v1/ai/actions/{action_id}/apply', {
          ...path,
          body: { confirm_high_risk: confirmHighRisk },
        })
      ).data!,
    onSuccess: (r) => {
      put(r.data);
      if (r.outcome === 'applied') void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'ai' });
    },
    onError: (e) => toastError(e, "Couldn't apply the changes"),
  });
  const reject = useMutation({
    mutationFn: async () => (await api.POST('/api/v1/ai/actions/{action_id}/reject', path)).data!.data,
    onSuccess: put,
    onError: (e) => toastError(e, "Couldn't dismiss the suggestion"),
  });
  const undo = useMutation({
    mutationFn: async () => (await api.POST('/api/v1/ai/actions/{action_id}/undo', path)).data!.data,
    onSuccess: (a) => {
      put(a);
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'ai' });
    },
    onError: (e) => toastError(e, "Couldn't undo"),
  });
  return { apply, reject, undo };
}

export type Conversation = components['schemas']['ConversationOut'];
export type ChatMessage = components['schemas']['ChatMessageOut'];
type FeedbackIn = components['schemas']['FeedbackIn'];

export const chatKeys = {
  list: ['ai', 'conversations'] as const,
  one: (id: string) => ['ai', 'conversations', id] as const,
};

/** My Ask Mo conversations, most recent first (S3.3.1). */
export function useConversations() {
  const api = useApi();
  return useQuery({
    queryKey: chatKeys.list,
    queryFn: async () => (await api.GET('/api/v1/ai/conversations')).data!.data,
  });
}

/** One conversation with its messages (citations re-checked for me by the server). */
export function useConversation(id: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: chatKeys.one(id ?? ''),
    enabled: Boolean(id),
    queryFn: async () =>
      (
        await api.GET('/api/v1/ai/conversations/{conversation_id}', {
          params: { path: { conversation_id: id! } },
        })
      ).data!,
  });
}

/** 👍/👎 on one of Mo's answers; a second rating replaces the first. */
export function useFeedback() {
  const api = useApi();
  return useMutation({
    mutationFn: async (body: FeedbackIn) => (await api.PUT('/api/v1/ai/feedback', { body })).data!,
    onError: (e) => toastError(e, "Couldn't save your rating"),
  });
}

export type SummaryResult = components['schemas']['SummaryOut'];

/** S3.4.1: summarize a task's comment thread, or my unread inbox (cached on the server by
 * content, so asking again for unchanged content is instant). */
export function useSummarize() {
  const api = useApi();
  return useMutation({
    mutationFn: async (body: components['schemas']['SummarizeIn']) =>
      (await api.POST('/api/v1/ai/summarize', { body })).data!,
  });
}

/** S3.4.2: Mo proposes subtasks for a task, as an AI action to review (creates nothing). */
export function useBreakdown(taskId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (hint: string | null) =>
      (
        await api.POST('/api/v1/ai/tasks/{task_id}/subtasks', {
          params: { path: { task_id: taskId } },
          body: { hint },
        })
      ).data!,
  });
}

/** S3.4.4: the editor's writing-help call, or undefined while AI is off (no Mo menu then). */
export function useWriteHelp(): ((req: components['schemas']['WriteIn']) => Promise<string>) | undefined {
  const api = useApi();
  const aiEnabled = useMomentumConfig().ai_enabled;
  return useMemo(
    () =>
      aiEnabled
        ? async (req: components['schemas']['WriteIn']) => {
            try {
              return (await api.POST('/api/v1/ai/write', { body: req })).data!.text;
            } catch (e) {
              throw new Error(errorText(e));
            }
          }
        : undefined,
    [api, aiEnabled],
  );
}

/** S3.4.5: Mo's plan for today, as a previewed change to My Tasks (`action_id` null when the
 * day already matches it). */
export function usePlanMyDay() {
  const api = useApi();
  return useMutation({
    mutationFn: async () => (await api.POST('/api/v1/ai/plan-my-day')).data!,
  });
}

/** S3.4.6: Mo's plan for a new project from a brief, as a previewed AI action. */
export function useProjectFromBrief() {
  const api = useApi();
  return useMutation({
    mutationFn: async (body: components['schemas']['FromBriefIn']) =>
      (await api.POST('/api/v1/ai/projects/from-brief', { body })).data!,
  });
}

// ---------------- admin: AI settings and usage (S3.5.2) ----------------

export type AdminAiSettings = components['schemas']['AdminAiSettingsOut'];
export type AiConfig = components['schemas']['AiConfig'];
export type UsageReport = components['schemas']['UsageReport'];

export const adminAiKeys = {
  settings: ['ai', 'admin', 'settings'] as const,
  usage: (days: number) => ['ai', 'admin', 'usage', days] as const,
};

/** The workspace's AI policy (admin only): raw overrides, what they resolve to, and the
 * deployment's model aliases (read-only). */
export function useAdminAiSettings() {
  const api = useApi();
  return useQuery({
    queryKey: adminAiKeys.settings,
    queryFn: async () => (await api.GET('/api/v1/ai/admin/settings')).data!,
  });
}

/** Change the workspace's AI policy (admin only). */
export function useAdminAiSettingsMutation() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: AiConfig) => (await api.PUT('/api/v1/ai/admin/settings', { body })).data!,
    onSuccess: () => void qc.invalidateQueries({ queryKey: adminAiKeys.settings }),
    onError: (e) => toastError(e, "Couldn't save AI settings"),
  });
}

/** Token/cost usage by feature, user and day over the last `days` (admin only). */
export function useAdminAiUsage(days = 30) {
  const api = useApi();
  return useQuery({
    queryKey: adminAiKeys.usage(days),
    queryFn: async () => (await api.GET('/api/v1/ai/admin/usage', { params: { query: { days } } })).data!,
  });
}
