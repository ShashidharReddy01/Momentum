import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useUndoToast } from '@/lib/undo';
import { useApi } from '@/providers/api';

export interface ShowIf {
  question_id: string;
  equals?: unknown;
}

export interface Question {
  id: string;
  label: string;
  help_text?: string | null;
  required: boolean;
  /** "title" | "description" | "assignee" | "due_on" | "priority" | a custom field id. */
  maps_to: string;
  show_if?: ShowIf | null;
}

export type FormOut = Omit<components['schemas']['FormOut'], 'questions'> & { questions: Question[] };
export type PublicForm = components['schemas']['PublicFormOut'];
export type PublicQuestion = components['schemas']['PublicQuestionOut'];

export interface FormSpec {
  name: string;
  description?: string | null;
  section_id?: string | null;
  questions: Question[];
  enabled: boolean;
  public_enabled: boolean;
  conversational: boolean;
}

export interface ConversationTurn {
  role: 'user' | 'assistant';
  text: string;
}

export type ConverseTurnOut = components['schemas']['ConverseTurnOut'];

export const formKeys = {
  byProject: (projectId: string) => ['projects', projectId, 'forms'] as const,
  one: (formId: string) => ['forms', formId] as const,
  public: (token: string) => ['public-forms', token] as const,
};

export function useForms(projectId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: formKeys.byProject(projectId),
    enabled: enabled && !!projectId,
    queryFn: async () =>
      (await api.GET('/api/v1/forms', { params: { query: { project_id: projectId } } })).data!
        .data as unknown as FormOut[],
  });
}

export function useForm(formId: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: formKeys.one(formId),
    enabled: enabled && !!formId,
    queryFn: async () =>
      (await api.GET('/api/v1/forms/{form_id}', { params: { path: { form_id: formId } } }))
        .data as unknown as FormOut,
  });
}

export function useFormMutations(projectId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const undoToast = useUndoToast();
  const key = formKeys.byProject(projectId);
  const settle = () => void qc.invalidateQueries({ queryKey: key });

  const create = useMutation({
    mutationFn: async (spec: FormSpec) =>
      (await api.POST('/api/v1/forms', { body: { ...spec, project_id: projectId } })).data!,
    onError: (e) => toastError(e, "Couldn't create the form"),
    onSettled: settle,
  });

  const update = useMutation({
    mutationFn: async (v: { id: string; patch: Partial<FormSpec> & { expected_version?: number } }) =>
      (
        await api.PATCH('/api/v1/forms/{form_id}', {
          params: { path: { form_id: v.id } },
          body: v.patch,
        })
      ).data!,
    onError: (e) => toastError(e, "Couldn't update the form"),
    onSettled: settle,
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      (await api.DELETE('/api/v1/forms/{form_id}', { params: { path: { form_id: id } } })).data!,
    onSuccess: (res) => undoToast('Form deleted', res.meta),
    onError: (e) => toastError(e, "Couldn't delete the form"),
    onSettled: settle,
  });

  return { create, update, remove };
}

/** The internal (logged-in) submission endpoint — the caller need only see the project. */
export function useSubmitFormInternal(formId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (answers: Record<string, unknown>) =>
      (
        await api.POST('/api/v1/forms/{form_id}/submit', {
          params: { path: { form_id: formId } },
          body: { answers, website: '' },
        })
      ).data!,
  });
}

/** The public link (S4.2.1): no session, so these hit `/public/forms/*` directly and never
 * touch the authenticated client's 401 handling (that path never returns one). */
export function usePublicForm(token: string) {
  const api = useApi();
  return useQuery({
    queryKey: formKeys.public(token),
    enabled: !!token,
    retry: false,
    queryFn: async () =>
      (await api.GET('/api/v1/public/forms/{token}', { params: { path: { token } } })).data!,
  });
}

export function useSubmitPublicForm(token: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (body: { answers: Record<string, unknown>; website: string }) =>
      (
        await api.POST('/api/v1/public/forms/{token}/submit', {
          params: { path: { token } },
          body,
        })
      ).data!,
  });
}

/** S4.2.2: one turn of the conversational intake, and the final confirm+submit. Stateless on
 * the server — the client resends the whole transcript each turn. */
export function useConverseInternal(formId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (history: ConversationTurn[]) =>
      (
        await api.POST('/api/v1/forms/{form_id}/converse', {
          params: { path: { form_id: formId } },
          body: { history },
        })
      ).data! as ConverseTurnOut,
  });
}

export function useConverseSubmitInternal(formId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (v: { history: ConversationTurn[]; answers: Record<string, unknown> }) =>
      (
        await api.POST('/api/v1/forms/{form_id}/converse/submit', {
          params: { path: { form_id: formId } },
          body: { ...v, website: '' },
        })
      ).data!,
  });
}

export function useConversePublic(token: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (history: ConversationTurn[]) =>
      (
        await api.POST('/api/v1/public/forms/{token}/converse', {
          params: { path: { token } },
          body: { history },
        })
      ).data! as ConverseTurnOut,
  });
}

export function useConverseSubmitPublic(token: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (v: { history: ConversationTurn[]; answers: Record<string, unknown> }) =>
      (
        await api.POST('/api/v1/public/forms/{token}/converse/submit', {
          params: { path: { token } },
          body: { ...v, website: '' },
        })
      ).data!,
  });
}
