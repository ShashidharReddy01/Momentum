import { useState } from 'react';
import { useParams } from 'react-router';
import { ApiError } from '@/lib/api/errors';
import { FormFiller } from './FormFiller';
import { usePublicForm, useSubmitPublicForm } from './queries';

/** The public link (S4.2.1): `/f/:token`, no login, its own route outside `AuthGate`/`Layout`.
 * A hidden `website` input is the honeypot — a real person never fills it in, and the server
 * fakes success rather than telling a bot it tripped a trap. */
export function PublicFormPage() {
  const { token = '' } = useParams();
  const form = usePublicForm(token);
  const submit = useSubmitPublicForm(token);
  const [done, setDone] = useState(false);
  const [website, setWebsite] = useState('');

  if (form.isPending) {
    return (
      <div className="p-8 text-sm text-muted" aria-busy>
        Loading…
      </div>
    );
  }
  if (form.isError || !form.data) {
    return (
      <div className="mx-auto max-w-lg p-8 text-center">
        <h1 className="text-lg font-semibold text-ink">This form isn't available</h1>
        <p className="mt-1 text-sm text-muted">
          The link may be wrong, or the form may no longer be accepting submissions.
        </p>
      </div>
    );
  }
  if (done) {
    return (
      <div className="mx-auto max-w-lg p-8 text-center">
        <h1 className="text-lg font-semibold text-ink">Thanks — got it.</h1>
        <p className="mt-1 text-sm text-muted">Your submission was recorded.</p>
      </div>
    );
  }

  return (
    <FormFiller
      name={form.data.name}
      description={form.data.description}
      questions={form.data.questions}
      submitting={submit.isPending}
      error={
        submit.isError
          ? submit.error instanceof ApiError
            ? (submit.error.problem.detail ?? 'Something went wrong. Try again.')
            : 'Something went wrong. Try again.'
          : null
      }
      onSubmit={(answers) => submit.mutate({ answers, website }, { onSuccess: () => setDone(true) })}
      extraFields={
        <input
          type="text"
          name="website"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
          className="absolute left-[-9999px] h-0 w-0 opacity-0"
        />
      }
    />
  );
}
