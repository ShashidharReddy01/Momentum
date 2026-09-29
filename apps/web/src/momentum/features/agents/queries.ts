import { useQuery } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { useApi } from '@/providers/api';

export type Agent = components['schemas']['AgentDetailOut'];
export type AgentRun = components['schemas']['AgentRunOut'];
export type AgentRunDetail = components['schemas']['AgentRunDetailOut'];
export type RunStep = components['schemas']['RunStepOut'];

export interface RunFilters {
  status?: string;
  trigger?: string;
}

export const agentKeys = {
  all: ['agents'] as const,
  detail: (id: string) => ['agents', id] as const,
  runs: (id: string, filters: RunFilters) => ['agents', id, 'runs', filters] as const,
  run: (runId: string) => ['agents', 'runs', runId] as const,
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
