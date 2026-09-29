import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { useProjectFields } from '@/features/fields';
import { useProject } from '@/features/projects';
import { ApiError } from '@/lib/api/errors';
import { ConversationalFiller } from './ConversationalFiller';
import { FormFiller } from './FormFiller';
import { renderQuestions } from './formMeta';
import { useConverseInternal, useConverseSubmitInternal, useForm, useSubmitFormInternal } from './queries';

/** The internal (logged-in) submission link: `/projects/:projectId/forms/:formId`, inside the
 * ordinary authenticated shell. The caller need only see the project (S4.2.1: intake is a
 * controlled channel — the task is always created as the form's owner, not the submitter). */
export function FormFillPage() {
  const { projectId = '', formId = '' } = useParams();
  const navigate = useNavigate();
  const form = useForm(formId);
  const fields = useProjectFields(projectId);
  // the assignee question offers the project's people, as the server checks (S5.0.2)
  const project = useProject(projectId);
  const submit = useSubmitFormInternal(formId);
  const converseTurn = useConverseInternal(formId);
  const converseSubmit = useConverseSubmitInternal(formId);
  const [done, setDone] = useState(false);

  if (form.isPending || fields.isPending || project.isPending) {
    return (
      <div className="p-8 text-sm text-muted" aria-busy>
        Loading…
      </div>
    );
  }
  if (form.isError || !form.data) {
    return <div className="mx-auto max-w-lg p-8 text-center text-sm text-muted">Form not found.</div>;
  }
  if (done) {
    return (
      <div className="mx-auto max-w-lg p-8 text-center">
        <h1 className="text-lg font-semibold text-ink">Thanks — got it.</h1>
        <button
          type="button"
          className="mt-3 text-sm text-accent underline"
          onClick={() => navigate(`/projects/${projectId}`)}
        >
          Back to the project
        </button>
      </div>
    );
  }

  if (form.data.conversational) {
    return (
      <ConversationalFiller
        name={form.data.name}
        description={form.data.description}
        converse={(history) => converseTurn.mutateAsync(history)}
        submit={(history, answers) => converseSubmit.mutateAsync({ history, answers })}
        onSubmitted={() => setDone(true)}
      />
    );
  }

  return (
    <FormFiller
      name={form.data.name}
      description={form.data.description}
      questions={renderQuestions(
        form.data.questions,
        fields.data ?? [],
        (project.data?.members ?? []).map((m) => m.user).filter((u) => !u.is_agent && u.status === 'active'),
      )}
      submitting={submit.isPending}
      error={
        submit.isError
          ? submit.error instanceof ApiError
            ? (submit.error.problem.detail ?? 'Something went wrong. Try again.')
            : 'Something went wrong. Try again.'
          : null
      }
      onSubmit={(answers) => submit.mutate(answers, { onSuccess: () => setDone(true) })}
    />
  );
}
