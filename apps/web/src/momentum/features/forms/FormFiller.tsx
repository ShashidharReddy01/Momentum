import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import type { PublicQuestion, ShowIf } from './queries';

/** What one question needs to render as an input, independent of whether it came from the
 * public endpoint's ready-made shape or was derived client-side for the internal link. */
export interface RenderQuestion {
  id: string;
  label: string;
  help_text?: string | null;
  required: boolean;
  kind: PublicQuestion['kind'];
  options?: { id: string; label: string }[] | null;
  people?: { id: string; label: string }[] | null;
  show_if?: ShowIf | null;
}

function isVisible(q: RenderQuestion, answers: Record<string, unknown>): boolean {
  if (!q.show_if) return true;
  return answers[q.show_if.question_id] === q.show_if.equals;
}

function Field({
  q,
  value,
  onChange,
}: {
  q: RenderQuestion;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const id = `form-q-${q.id}`;
  if (q.kind === 'long_text') {
    return (
      <textarea
        id={id}
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        maxLength={5000}
        className="w-full rounded-md border border-hairline bg-surface-2 px-2.5 py-1.5 text-sm placeholder:text-muted-2 focus:border-focus focus:outline-none"
      />
    );
  }
  if (q.kind === 'checkbox') {
    return (
      <input
        id={id}
        type="checkbox"
        checked={value === true}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4"
      />
    );
  }
  if (q.kind === 'date') {
    return (
      <Input
        id={id}
        type="date"
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  if (q.kind === 'number') {
    return (
      <Input
        id={id}
        type="number"
        value={typeof value === 'number' ? value : ''}
        onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
      />
    );
  }
  if (q.kind === 'select' || q.kind === 'person') {
    const options = q.kind === 'person' ? (q.people ?? []) : (q.options ?? []);
    return (
      <select
        id={id}
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value || undefined)}
        className="h-8 w-full rounded-md border border-hairline bg-surface-2 px-2.5 text-sm focus:border-focus focus:outline-none"
      >
        <option value="">{q.required ? 'Choose one…' : "Don't set"}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }
  if (q.kind === 'multi_select') {
    const selected = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="flex flex-wrap gap-2">
        {(q.options ?? []).map((o) => (
          <label key={o.id} className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              checked={selected.includes(o.id)}
              onChange={(e) =>
                onChange(e.target.checked ? [...selected, o.id] : selected.filter((v) => v !== o.id))
              }
            />
            {o.label}
          </label>
        ))}
      </div>
    );
  }
  return (
    <Input
      id={id}
      value={typeof value === 'string' ? value : ''}
      onChange={(e) => onChange(e.target.value)}
      maxLength={500}
    />
  );
}

/** Renders a form's questions in order, applying branching (show_if) client-side, and submits
 * `{ answers }` when everything required and visible has a value. Shared by the public page
 * (`/f/:token`) and the internal (logged-in) fill page. */
export function FormFiller({
  name,
  description,
  questions,
  submitting,
  error,
  onSubmit,
  extraFields,
}: {
  name: string;
  description?: string | null;
  questions: RenderQuestion[];
  submitting: boolean;
  error?: string | null;
  onSubmit: (answers: Record<string, unknown>) => void;
  /** The honeypot input on the public page; omitted internally. */
  extraFields?: React.ReactNode;
}) {
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const visible = questions.filter((q) => isVisible(q, answers));
  const missing = visible.filter((q) => {
    if (!q.required) return false;
    const v = answers[q.id];
    return v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0);
  });

  return (
    <form
      className="mx-auto flex w-full max-w-lg flex-col gap-4 p-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (missing.length > 0) return;
        const clean: Record<string, unknown> = {};
        for (const q of visible) if (answers[q.id] !== undefined) clean[q.id] = answers[q.id];
        onSubmit(clean);
      }}
    >
      <div>
        <h1 className="text-lg font-semibold text-ink">{name}</h1>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {visible.map((q) => (
        <div key={q.id} className="flex flex-col gap-1">
          <label htmlFor={`form-q-${q.id}`} className="text-sm font-medium text-ink">
            {q.label}
            {q.required ? <span className="text-crit"> *</span> : null}
          </label>
          {q.help_text ? <p className="text-xs text-muted">{q.help_text}</p> : null}
          <Field q={q} value={answers[q.id]} onChange={(v) => setAnswers((a) => ({ ...a, [q.id]: v }))} />
        </div>
      ))}
      {extraFields}
      {error ? (
        <p role="alert" className="text-sm text-crit">
          {error}
        </p>
      ) : null}
      <Button type="submit" loading={submitting} disabled={missing.length > 0}>
        Submit
      </Button>
    </form>
  );
}
