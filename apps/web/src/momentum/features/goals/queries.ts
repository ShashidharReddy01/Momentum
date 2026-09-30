import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export type Goal = components['schemas']['GoalOut'];
export type GoalDetail = components['schemas']['GoalDetailOut'];
export type GoalIn = components['schemas']['GoalIn'];
export type GoalPatch = components['schemas']['GoalPatchIn'];
export type GoalCheckIn = components['schemas']['GoalCheckInIn'];

export const goalKeys = {
  all: ['goals'] as const,
  list: ['goals', 'list'] as const,
  detail: (id: string) => ['goals', id] as const,
  checkIns: (id: string) => ['goals', id, 'check-ins'] as const,
};

export function useGoals() {
  const api = useApi();
  return useQuery({
    queryKey: goalKeys.list,
    queryFn: async () => (await api.GET('/api/v1/goals')).data!.data,
  });
}

export function useGoal(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: goalKeys.detail(id),
    queryFn: async () =>
      (await api.GET('/api/v1/goals/{goal_id}', { params: { path: { goal_id: id } } })).data!,
  });
}

export function useGoalCheckIns(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: goalKeys.checkIns(id),
    queryFn: async () =>
      (await api.GET('/api/v1/goals/{goal_id}/check-ins', { params: { path: { goal_id: id } } })).data!.data,
  });
}

export function useCreateGoal() {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  return useMutation({
    mutationFn: async (body: GoalIn) => (await api.POST('/api/v1/goals', { body })).data!,
    onSuccess: (res) => {
      undoToast('Goal created', res.meta, () => void qc.invalidateQueries({ queryKey: goalKeys.all }));
      void qc.invalidateQueries({ queryKey: goalKeys.all });
    },
    onError: (e) => toastError(e, "Couldn't create the goal"),
  });
}

/** Edits to one goal; each returns the fresh detail (with progress recomputed) and offers Undo. */
export function useGoalMutations(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const path = { goal_id: id };
  const refresh = () => void qc.invalidateQueries({ queryKey: goalKeys.all });
  const settle = (message: string) => ({
    onSuccess: (res: { data: GoalDetail; meta: components['schemas']['MutationMeta'] }) => {
      qc.setQueryData(goalKeys.detail(id), res.data);
      undoToast(message, res.meta, refresh);
      void qc.invalidateQueries({ queryKey: goalKeys.list });
    },
    onError: (e: unknown) => toastError(e, "Couldn't update the goal"),
  });
  const update = useMutation({
    mutationFn: async (body: GoalPatch) =>
      (await api.PATCH('/api/v1/goals/{goal_id}', { params: { path }, body })).data!,
    ...settle('Goal updated'),
  });
  const link = useMutation({
    mutationFn: async (v: { entity_type: 'project' | 'portfolio'; entity_id: string }) =>
      (await api.POST('/api/v1/goals/{goal_id}/links', { params: { path }, body: v })).data!,
    ...settle('Linked'),
  });
  const unlink = useMutation({
    mutationFn: async (v: { entity_type: 'project' | 'portfolio'; entity_id: string }) =>
      (
        await api.DELETE('/api/v1/goals/{goal_id}/links/{entity_type}/{entity_id}', {
          params: { path: { ...path, ...v } },
        })
      ).data!,
    ...settle('Unlinked'),
  });
  const checkIn = useMutation({
    mutationFn: async (body: GoalCheckIn) =>
      (await api.POST('/api/v1/goals/{goal_id}/check-ins', { params: { path }, body })).data!,
    onSuccess: (res) => {
      undoToast('Checked in', res.meta, refresh);
      refresh();
    },
    onError: (e) => toastError(e, "Couldn't check in"),
  });
  return { update, link, unlink, checkIn };
}

/** Calendar quarters around today: the one we're in, the one before, and three ahead. */
export function quarters(today = new Date()): { label: string; start: string; end: string }[] {
  const pad = (n: number) => String(n).padStart(2, '0');
  const q0 = Math.floor(today.getMonth() / 3);
  return [-1, 0, 1, 2, 3].map((offset) => {
    const idx = today.getFullYear() * 4 + q0 + offset;
    const year = Math.floor(idx / 4);
    const q = idx % 4;
    const endMonth = q * 3 + 3;
    const lastDay = new Date(year, endMonth, 0).getDate();
    return {
      label: `Q${q + 1} ${year}`,
      start: `${year}-${pad(q * 3 + 1)}-01`,
      end: `${year}-${pad(endMonth)}-${pad(lastDay)}`,
    };
  });
}

export type GoalSuggestion = components['schemas']['GoalLinkSuggestionOut'];

/** S6.3.2: Mo drafts a check-in from the goal's numbers, and suggests projects that support it.
 * Both only propose: nothing is posted or linked until the person does it. */
export function useGoalAi(id: string) {
  const api = useApi();
  const path = { goal_id: id };
  const draft = useMutation({
    mutationFn: async () =>
      (await api.POST('/api/v1/ai/goals/{goal_id}/check-in-draft', { params: { path } })).data!,
    onError: (e) => toastError(e, "Mo couldn't draft the check-in"),
  });
  const suggest = useMutation({
    mutationFn: async () =>
      (await api.POST('/api/v1/ai/goals/{goal_id}/suggest-links', { params: { path } })).data!.suggestions,
    onError: (e) => toastError(e, "Mo couldn't look for projects"),
  });
  return { draft, suggest };
}
