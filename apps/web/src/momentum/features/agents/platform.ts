import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

/** Phase 7.6 S76-07: the agent platform on the web: the directory, an agent's profile, health
 * and pack settings, jobs on a task, and agents' questions (asks). */

export type DirectoryCard = components['schemas']['DirectoryCardOut'];
export type AgentProfile = components['schemas']['ProfileOut'];
export type AgentHealth = components['schemas']['HealthOut'];
export type PackSettings = components['schemas']['PackSettingsOut'];
export type TaskJob = components['schemas']['TaskJobOut'];
export type Ask = components['schemas']['AskOut'];
export type Interpretation = components['schemas']['InterpretOut'];
export type UndoAll = components['schemas']['UndoAllOut'];

export interface DirectoryFilters {
  q?: string;
  capability?: string;
  data_class?: string;
  enabled?: boolean;
}

export const platformKeys = {
  directory: (f: DirectoryFilters) => ['agents', 'directory', f] as const,
  directoryAll: ['agents', 'directory'] as const,
  profile: (id: string) => ['agents', id, 'profile'] as const,
  health: (id: string, days: number) => ['agents', id, 'health', days] as const,
  settings: (id: string, projectId: string | null) => ['agents', id, 'settings', projectId] as const,
  taskJobs: (taskId: string) => ['tasks', taskId, 'jobs'] as const,
  ask: (id: string) => ['asks', id] as const,
  myAsks: ['asks', 'mine'] as const,
};

export function useDirectory(filters: DirectoryFilters, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.directory(filters),
    enabled,
    queryFn: async () =>
      (
        await api.GET('/api/v1/agents/directory', {
          params: {
            query: {
              q: filters.q || undefined,
              capability: filters.capability || undefined,
              data_class: filters.data_class || undefined,
              enabled: filters.enabled,
            },
          },
        })
      ).data!.data,
    placeholderData: (prev) => prev,
  });
}

export function useAgentProfile(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.profile(id),
    queryFn: async () =>
      (await api.GET('/api/v1/agents/{agent_id}/profile', { params: { path: { agent_id: id } } })).data!,
  });
}

export function useAgentHealth(id: string, days: number, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.health(id, days),
    enabled,
    queryFn: async () =>
      (
        await api.GET('/api/v1/agents/{agent_id}/health', {
          params: { path: { agent_id: id }, query: { days } },
        })
      ).data!,
  });
}

export function usePackSettings(id: string, projectId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.settings(id, projectId),
    queryFn: async () =>
      (
        await api.GET('/api/v1/agents/{agent_id}/settings', {
          params: { path: { agent_id: id }, query: { project_id: projectId ?? undefined } },
        })
      ).data!,
  });
}

export function useSavePackSettings(id: string, projectId: string | null) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (values: Record<string, unknown>) =>
      (
        await api.PUT('/api/v1/agents/{agent_id}/settings', {
          params: { path: { agent_id: id }, query: { project_id: projectId ?? undefined } },
          body: { values },
        })
      ).data!,
    onSuccess: (data) => {
      qc.setQueryData(platformKeys.settings(id, projectId), data);
      void qc.invalidateQueries({ queryKey: ['agents', id, 'settings'] });
    },
    onError: (e) => toastError(e, "Couldn't save the settings"),
  });
}

export function useTaskJobs(taskId: string) {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.taskJobs(taskId),
    queryFn: async () =>
      (await api.GET('/api/v1/tasks/{task_id}/jobs', { params: { path: { task_id: taskId } } })).data!.data,
  });
}

export type JobAction = 'retry' | 'cancel' | 'pause' | 'resume';

/** Pause, resume, cancel or retry a job; the server checks who may. */
export function useJobControl(runId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const done = () => {
    void qc.invalidateQueries({ queryKey: ['agents', 'runs', runId] });
    void qc.invalidateQueries({ queryKey: ['tasks'], predicate: (q) => q.queryKey[2] === 'jobs' });
  };
  return {
    act: useMutation({
      mutationFn: async (action: JobAction) => {
        const path = { params: { path: { run_id: runId } } };
        const r =
          action === 'retry'
            ? await api.POST('/api/v1/agents/runs/{run_id}/retry', path)
            : action === 'cancel'
              ? await api.POST('/api/v1/agents/runs/{run_id}/cancel', path)
              : action === 'pause'
                ? await api.POST('/api/v1/agents/runs/{run_id}/pause', path)
                : await api.POST('/api/v1/agents/runs/{run_id}/resume', path);
        return r.data!;
      },
      onSuccess: done,
      onError: (e) => toastError(e, "Couldn't change the job"),
    }),
    undoAll: useMutation({
      mutationFn: async () =>
        (await api.POST('/api/v1/agents/runs/{run_id}/undo', { params: { path: { run_id: runId } } })).data!,
      onSuccess: () => {
        done();
        void qc.invalidateQueries({ queryKey: ['tasks'] });
      },
      onError: (e) => toastError(e, "Couldn't undo the job's changes"),
    }),
  };
}

export function useAsk(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.ask(id),
    queryFn: async () => (await api.GET('/api/v1/asks/{ask_id}', { params: { path: { ask_id: id } } })).data!,
  });
}

/** Open questions agents are waiting on me for, oldest first. */
export function useMyAsks(enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: platformKeys.myAsks,
    enabled,
    queryFn: async () => {
      const rows = (await api.GET('/api/v1/asks', { params: { query: { mine: true, status: 'open' } } }))
        .data!.data;
      return [...rows].sort((a, b) => a.created_at.localeCompare(b.created_at));
    },
  });
}

function settleAsk(qc: ReturnType<typeof useQueryClient>, ask: Ask) {
  qc.setQueryData(platformKeys.ask(ask.id), ask);
  void qc.invalidateQueries({ queryKey: platformKeys.myAsks });
  void qc.invalidateQueries({ queryKey: platformKeys.taskJobs(ask.task_id) });
}

export function useAnswerAsk(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ value, via }: { value: unknown; via: 'card' | 'thread' | 'inbox' }) =>
      (
        await api.POST('/api/v1/asks/{ask_id}/answer', {
          params: { path: { ask_id: id } },
          body: { value, via },
        })
      ).data!,
    onSuccess: (ask) => settleAsk(qc, ask),
    onError: (e) => toastError(e, "Couldn't send the answer"),
  });
}

/** A thread reply read as the answer: applied when certain, otherwise returned to confirm. */
export function useInterpretReply() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ askId, text }: { askId: string; text: string }) =>
      (
        await api.POST('/api/v1/asks/{ask_id}/interpret', {
          params: { path: { ask_id: askId } },
          body: { text },
        })
      ).data!,
    onSuccess: (r) => settleAsk(qc, r.ask),
    onError: (e) => toastError(e, "Couldn't read your reply as the answer"),
  });
}

/** Plain text of a rich-text doc (Tiptap JSON), for reading a reply as an answer. */
export function docText(node: unknown): string {
  if (!node || typeof node !== 'object') return '';
  const n = node as { type?: string; text?: string; content?: unknown[]; attrs?: { label?: string } };
  if (n.type === 'text') return n.text ?? '';
  if (n.type === 'mention') return `@${n.attrs?.label ?? ''}`;
  const inner = (n.content ?? []).map(docText);
  return n.type === 'doc' ? inner.join('\n').trim() : inner.join('');
}

/** "Change": take an answer back (undo it) while the agent hasn't used it; the card reopens. */
export function useChangeAnswer(ask: Ask) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.POST('/api/v1/undo', { body: { activity_id: ask.change_activity_id! } });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: platformKeys.ask(ask.id) });
      void qc.invalidateQueries({ queryKey: platformKeys.myAsks });
    },
    onError: (e) => toastError(e, "Couldn't reopen the question"),
  });
}
