import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toastError } from '@/lib/toast';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';

export type Agent = components['schemas']['AgentDetailOut'];
export type AgentRun = components['schemas']['AgentRunOut'];
export type AgentRunDetail = components['schemas']['AgentRunDetailOut'];
export type RunStep = components['schemas']['RunStepOut'];
export type AgentStats = components['schemas']['AgentStatsOut'];
export type AgentPatch = components['schemas']['AgentPatchIn'];

export interface RunFilters {
  status?: string;
  trigger?: string;
}

export const agentKeys = {
  all: ['agents'] as const,
  detail: (id: string) => ['agents', id] as const,
  runs: (id: string, filters: RunFilters) => ['agents', id, 'runs', filters] as const,
  run: (runId: string) => ['agents', 'runs', runId] as const,
  stats: (id: string) => ['agents', id, 'stats'] as const,
};

/** A run that hasn't finished yet refreshes itself; agents start within a minute. */
const POLL_MS = 5_000;
const LIVE = new Set(['queued', 'running']);

export function useAgent(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: agentKeys.detail(id),
    queryFn: async () =>
      (await api.GET('/api/v1/agents/{agent_id}', { params: { path: { agent_id: id } } })).data!,
  });
}

export function useAgentRuns(id: string, filters: RunFilters) {
  const api = useApi();
  return useQuery({
    queryKey: agentKeys.runs(id, filters),
    queryFn: async () =>
      (
        await api.GET('/api/v1/agents/{agent_id}/runs', {
          params: {
            path: { agent_id: id },
            query: { status: filters.status || undefined, trigger: filters.trigger || undefined },
          },
        })
      ).data!.data,
    refetchInterval: (q) => (q.state.data?.some((r) => LIVE.has(r.status)) ? POLL_MS : false),
  });
}

export function useAgentRun(runId: string) {
  const api = useApi();
  return useQuery({
    queryKey: agentKeys.run(runId),
    queryFn: async () =>
      (await api.GET('/api/v1/agents/runs/{run_id}', { params: { path: { run_id: runId } } })).data!,
    refetchInterval: (q) => (q.state.data && LIVE.has(q.state.data.status) ? POLL_MS : false),
  });
}

/** S5.1.4: the track record behind the autonomy setting, and this month's spend (admins). */
export function useAgentStats(id: string, enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: agentKeys.stats(id),
    enabled,
    queryFn: async () =>
      (await api.GET('/api/v1/agents/{agent_id}/stats', { params: { path: { agent_id: id } } })).data!,
  });
}

export function useUpdateAgent(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (patch: AgentPatch) =>
      (
        await api.PATCH('/api/v1/agents/{agent_id}', {
          params: { path: { agent_id: id } },
          body: patch,
        })
      ).data!,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: agentKeys.all });
      void qc.invalidateQueries({ queryKey: agentKeys.stats(id) });
    },
    onError: (e) => toastError(e, "Couldn't save the agent"),
  });
}

// ---------- S5.2.3: gallery, create/edit, draft from a description, test run ----------

export type AgentIn = components['schemas']['AgentIn-Input'];
export type AgentDraft = components['schemas']['AgentDraftOut'];
export type AgentTool = components['schemas']['AgentToolOut'];
export type TestRun = components['schemas']['TestRunOut'];
export type TestRunIn = components['schemas']['TestRunIn'];

export function useAgents() {
  const api = useApi();
  return useQuery({
    queryKey: agentKeys.all,
    queryFn: async () => (await api.GET('/api/v1/agents')).data!.data,
  });
}

export function useAgentTools() {
  const api = useApi();
  return useQuery({
    queryKey: ['agents', 'tools'],
    queryFn: async () => (await api.GET('/api/v1/agents/tools')).data!.data,
    staleTime: 5 * 60_000,
  });
}

export function useInstallAgents() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.POST('/api/v1/agents/install', { body: { force: false } })).data!,
    onSuccess: () => void qc.invalidateQueries({ queryKey: agentKeys.all }),
    onError: (e) => toastError(e, "Couldn't install the starter agents"),
  });
}

export function useCreateAgent() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: AgentIn) => (await api.POST('/api/v1/agents', { body })).data!,
    onSuccess: () => void qc.invalidateQueries({ queryKey: agentKeys.all }),
    onError: (e) => toastError(e, "Couldn't create the agent"),
  });
}

/** "✦ Describe what you want": Mo drafts a definition; nothing is saved. */
export function useDraftAgent() {
  const api = useApi();
  return useMutation({
    mutationFn: async (description: string) =>
      (await api.POST('/api/v1/agents/draft', { body: { description } })).data!,
  });
}

/** A dry run on a task or project: what the agent would say and change; nothing is changed. */
export function useTestRun(id: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (body: TestRunIn) =>
      (
        await api.POST('/api/v1/agents/{agent_id}/test-run', {
          params: { path: { agent_id: id } },
          body,
        })
      ).data!,
  });
}
