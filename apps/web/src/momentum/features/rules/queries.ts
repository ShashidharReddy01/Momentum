import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

/** The stored shape is looser than the write schema (`RuleOut.trigger`/`conditions`/`actions`
 * come back as untyped JSON), so reads are cast to these — the same shape the write side
 * (`Trigger`/`Condition`/`Action`) validates against. */
export interface RuleTrigger {
  type: string;
  to_section?: string | null;
  field?: string | null;
  to?: unknown;
  user_id?: string | null;
  /** form.submitted (S4.2.1): null/omitted matches any form in the project. */
  form_id?: string | null;
  /** approval.decided (S4.4.1): null/omitted matches any decision. */
  decision?: string | null;
}
export interface RuleCondition {
  field: string;
  op: string;
  value?: unknown;
}
export interface RuleAction {
  type: string;
  user_id?: string | null;
  text?: string | null;
  section_id?: string | null;
  field_id?: string | null;
  value?: unknown;
  project_id?: string | null;
  tag_id?: string | null;
  titles?: string[] | null;
  days?: number | null;
  /** S4.1.5 `ai_step`: which AI step to run (see `AI_STEP_KINDS` in `ruleMeta.ts`). */
  kind?: string | null;
}

export type RuleOut = Omit<components['schemas']['RuleOut'], 'trigger' | 'conditions' | 'actions'> & {
  trigger: RuleTrigger;
  conditions: RuleCondition[];
  actions: RuleAction[];
};
export type RuleRun = components['schemas']['RuleRunOut'];
export type RuleAiStep = components['schemas']['RuleAiStepOut'];
export type RuleTestRun = components['schemas']['RuleTestRunOut'];

export interface RuleSpec {
  name: string;
  enabled: boolean;
  trigger: RuleTrigger;
  conditions: RuleCondition[];
  actions: RuleAction[];
  /** Set only on a rule Mo compiled from a sentence (S4.1.4); never sent on an edit. */
  created_from_prompt?: string | null;
}

/** S4.1.4: what `POST /ai/rules/compile` answers with — a draft the builder can show as-is, or a
 * question Mo asks instead of guessing. Never both. */
export interface CompiledRule {
  rule: RuleSpec | null;
  sentence: string | null;
  question: string | null;
}

export const ruleKeys = {
  byProject: (projectId: string) => ['projects', projectId, 'rules'] as const,
  runs: (ruleId: string) => ['rules', ruleId, 'runs'] as const,
};

/** A project's own rules (S4.1.3 doesn't build the workspace-rules screen yet). */
export function useRules(projectId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: ruleKeys.byProject(projectId),
    enabled: enabled && !!projectId,
    queryFn: async () =>
      (await api.GET('/api/v1/rules', { params: { query: { project_id: projectId } } })).data!
        .data as unknown as RuleOut[],
  });
}

export function useRuleRuns(ruleId: string, enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: ruleKeys.runs(ruleId),
    enabled: enabled && !!ruleId,
    queryFn: async () =>
      (await api.GET('/api/v1/rules/{rule_id}/runs', { params: { path: { rule_id: ruleId } } })).data!.data,
  });
}

/** Rule changes are configuration, not task data: no undo (mirrors fields/tags — see
 * `domain/rules/service.py`'s module doc comment). */
export function useRuleMutations(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const key = ruleKeys.byProject(projectId);
  const settle = () => void qc.invalidateQueries({ queryKey: key });

  const create = useMutation({
    mutationFn: async (spec: RuleSpec) =>
      (await api.POST('/api/v1/rules', { body: { ...spec, project_id: projectId } })).data!,
    onError: (e) => toastError(e, "Couldn't create the rule"),
    onSettled: settle,
  });

  const update = useMutation({
    mutationFn: async (v: { id: string; patch: Partial<RuleSpec> }) =>
      (
        await api.PATCH('/api/v1/rules/{rule_id}', {
          params: { path: { rule_id: v.id } },
          body: v.patch,
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't update the rule"),
    onSettled: settle,
  });

  const setEnabled = useMutation({
    mutationFn: async (v: { id: string; enabled: boolean }) =>
      (
        await api.PATCH('/api/v1/rules/{rule_id}', {
          params: { path: { rule_id: v.id } },
          body: { enabled: v.enabled },
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't update the rule"),
    onSettled: settle,
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      await api.DELETE('/api/v1/rules/{rule_id}', { params: { path: { rule_id: id } } }),
    onError: (e) => toastError(e, "Couldn't delete the rule"),
    onSettled: settle,
  });

  return { create, update, setEnabled, remove };
}

/** S4.1.4 "describe it": a sentence → a rule draft for the builder (the draft is saved through
 * the normal create endpoint, so there's no second write path). Errors show inline, not as a
 * toast: the box the user typed in is right there. */
export function useCompileRule(projectId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (text: string) =>
      (
        await api.POST('/api/v1/ai/rules/compile', {
          body: { project_id: projectId, text },
        })
      ).data! as unknown as CompiledRule,
  });
}

export function useTestRun(ruleId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (taskId: string) =>
      (
        await api.POST('/api/v1/rules/{rule_id}/test-run', {
          params: { path: { rule_id: ruleId } },
          body: { task_id: taskId },
        })
      ).data! as RuleTestRun,
    onError: (e) => toastError(e, "Couldn't test the rule"),
  });
}
