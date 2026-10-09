import { useState, type FormEvent } from 'react';
import { MoMark } from '@/components/common/MoMark';
import { AIMockMark } from '@/components/common/AI';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/dates';
import { useAnswerAsk, useAsk, useChangeAnswer, type Ask } from './platform';

type Via = 'card' | 'thread' | 'inbox';
type Opt = { value: string; label: string; description?: string | null };
type Field = {
  name: string;
  label: string;
  type: string;
  required?: boolean;
  default?: unknown;
  options?: string[] | null;
};

const PICK = new Set(['choice', 'pick_entity', 'pick_record']);

/** An answer in words: the option's label, Yes/No, the text, or "Field = value" pairs. */
export function describeAnswer(ask: Pick<Ask, 'kind' | 'options' | 'form' | 'answer'>): string {
  const a = ask.answer;
  if (a == null) return '';
  if (PICK.has(ask.kind)) {
    const opt = ((ask.options ?? []) as Opt[]).find((o) => o.value === a);
    return opt?.label ?? String(a);
  }
  if (ask.kind === 'confirm') return a ? 'Yes' : 'No';
  if (ask.kind === 'form' && typeof a === 'object') {
    const fields = (ask.form ?? []) as Field[];
    return Object.entries(a as Record<string, unknown>)
      .filter(([, v]) => v != null && v !== '')
      .map(([k, v]) => `${fields.find((f) => f.name === k)?.label ?? k} = ${String(v)}`)
      .join(', ');
  }
  return String(a);
}

/** The ask card in a task's thread (spec §5.2): the agent's question with its answer controls
 * inline. Answered cards collapse to who answered and what, with "Change" while the agent hasn't
 * used the answer yet. */
export function AskCard({ askId }: { askId: string }) {
  const ask = useAsk(askId);
  if (ask.isPending) return <Skeleton className="my-1 h-20" />;
  if (ask.isError) return <p className="text-xs text-muted">This question isn’t available.</p>;
  return <AskBox ask={ask.data} via="card" />;
}

export function AskBox({ ask, via, compact = false }: { ask: Ask; via: Via; compact?: boolean }) {
  const open = ask.status === 'open';
  return (
    <section
      aria-label={`${ask.agent.name} asks: ${ask.title}`}
      className={cn(
        'my-1 rounded-lg border bg-amber-2/40 px-3 py-2 text-sm not-prose',
        open ? 'border-amber ring-1 ring-amber/40' : 'border-hairline',
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5 text-xs font-semibold text-amber-ink">
        <MoMark size={12} /> {ask.agent.name} asks <AIMockMark />
        {open && !compact ? (
          <span className="ml-auto font-normal text-muted">
            for {ask.to.map((p) => p.name).join(', ') || 'someone'} · {formatRelative(ask.created_at)}
          </span>
        ) : null}
      </div>
      <p className="mt-0.5 font-medium text-ink">{ask.title}</p>
      {ask.body && !compact ? <p className="whitespace-pre-wrap text-ink-2">{ask.body}</p> : null}
      {!compact && ask.evidence.length ? (
        <ul aria-label="Evidence" className="mt-1 flex flex-wrap gap-1.5 text-xs text-muted">
          {ask.evidence.map((e, i) => (
            <li key={i} className="rounded border border-hairline px-1.5 py-0.5">
              {e.page != null ? `Page ${String(e.page)}` : 'Evidence'}
              {e.excerpt ? `: “${String(e.excerpt)}”` : ''}
            </li>
          ))}
        </ul>
      ) : null}
      {open ? (
        ask.can_answer ? (
          <AskControls ask={ask} via={via} />
        ) : (
          <p className="mt-1 text-xs text-muted">Waiting for {ask.to.map((p) => p.name).join(', ')}.</p>
        )
      ) : (
        <AskOutcome ask={ask} />
      )}
    </section>
  );
}

function AskOutcome({ ask }: { ask: Ask }) {
  const change = useChangeAnswer(ask);
  if (ask.status !== 'answered') {
    return (
      <p className="mt-1 text-xs text-muted">
        {ask.status === 'expired'
          ? 'No one answered in time; the agent used its fallback.'
          : ask.status === 'cancelled'
            ? 'The agent no longer needs this.'
            : `This question is ${ask.status}.`}
      </p>
    );
  }
  return (
    <p className="mt-1 text-xs text-ink-2">
      {ask.answered_via === 'thread' ? 'Understood' : 'Answered'}
      {ask.answered_by ? ` by ${ask.answered_by.name}` : ''}: <em>{describeAnswer(ask)}</em>
      {ask.change_activity_id ? (
        <button
          type="button"
          className="ml-2 text-accent hover:underline disabled:opacity-50"
          disabled={change.isPending}
          onClick={() => change.mutate()}
        >
          Change
        </button>
      ) : null}
    </p>
  );
}

/** The inline answer controls for one question (card, inbox row). */
export function AskControls({ ask, via }: { ask: Ask; via: Via }) {
  const answer = useAnswerAsk(ask.id);
  const send = (value: unknown) => answer.mutate({ value, via });
  if (PICK.has(ask.kind)) {
    return (
      <div role="group" aria-label="Answer" className="mt-2 flex flex-wrap gap-1.5">
        {((ask.options ?? []) as Opt[]).map((o) => (
          <Button
            key={o.value}
            size="sm"
            title={o.description ?? undefined}
            disabled={answer.isPending}
            onClick={() => send(o.value)}
          >
            {o.label}
          </Button>
        ))}
      </div>
    );
  }
  if (ask.kind === 'confirm') {
    return (
      <div role="group" aria-label="Answer" className="mt-2 flex gap-1.5">
        <Button size="sm" variant="primary" disabled={answer.isPending} onClick={() => send(true)}>
          Yes
        </Button>
        <Button size="sm" disabled={answer.isPending} onClick={() => send(false)}>
          No
        </Button>
      </div>
    );
  }
  if (ask.kind === 'text') return <TextAnswer pending={answer.isPending} onSend={send} />;
  return <FormAnswer fields={(ask.form ?? []) as Field[]} pending={answer.isPending} onSend={send} />;
}

function TextAnswer({ pending, onSend }: { pending: boolean; onSend: (v: string) => void }) {
  const [text, setText] = useState('');
  return (
    <form
      className="mt-2 flex gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) onSend(text.trim());
      }}
    >
      <input
        aria-label="Your answer"
        className="h-7 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-2 text-sm"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <Button size="sm" variant="primary" type="submit" disabled={pending || !text.trim()}>
        Send
      </Button>
    </form>
  );
}

function FormAnswer({
  fields,
  pending,
  onSend,
}: {
  fields: Field[];
  pending: boolean;
  onSend: (v: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, f.default ?? (f.type === 'boolean' ? false : '')])),
  );
  const set = (name: string, v: unknown) => setValues((cur) => ({ ...cur, [name]: v }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSend(values);
  };
  return (
    <form className="mt-2 grid gap-2 sm:grid-cols-2" onSubmit={submit}>
      {fields.map((f) => {
        const id = `ask-${f.name}`;
        const v = values[f.name];
        return (
          <label key={f.name} htmlFor={id} className="flex flex-col gap-0.5 text-xs text-muted">
            <span>
              {f.label}
              {f.required === false ? ' (optional)' : ''}
            </span>
            {f.type === 'enum' ? (
              <select
                id={id}
                className="h-7 rounded-md border border-hairline bg-surface px-1 text-sm text-ink"
                value={String(v ?? '')}
                onChange={(e) => set(f.name, e.target.value)}
              >
                <option value="">Choose…</option>
                {(f.options ?? []).map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : f.type === 'boolean' ? (
              <input id={id} type="checkbox" checked={!!v} onChange={(e) => set(f.name, e.target.checked)} />
            ) : (
              <input
                id={id}
                type={f.type === 'date' ? 'date' : 'text'}
                inputMode={f.type === 'number' || f.type === 'money' ? 'decimal' : undefined}
                className="h-7 rounded-md border border-hairline bg-surface px-2 text-sm text-ink"
                value={String(v ?? '')}
                onChange={(e) => set(f.name, e.target.value)}
              />
            )}
          </label>
        );
      })}
      <div className="sm:col-span-2">
        <Button size="sm" variant="primary" type="submit" disabled={pending}>
          Send
        </Button>
      </div>
    </form>
  );
}
