import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import type { ConversationTurn, ConverseTurnOut } from './queries';

/** S4.2.2: a chat UI for a form's conversational link. Stateless on the server — this component
 * holds the transcript and resends it each turn — so a page refresh starts over, like any
 * in-page chat that isn't persisted. Shared by the public `/f/:token` page and the internal
 * `/projects/:id/forms/:formId` page; only the `converse`/`submit` functions differ. */
export function ConversationalFiller({
  name,
  description,
  converse,
  submit,
  onSubmitted,
}: {
  name: string;
  description?: string | null;
  converse: (history: ConversationTurn[]) => Promise<ConverseTurnOut>;
  submit: (history: ConversationTurn[], answers: Record<string, unknown>) => Promise<unknown>;
  onSubmitted: () => void;
}) {
  const [history, setHistory] = useState<ConversationTurn[]>([]);
  const [input, setInput] = useState('');
  const [pendingAnswers, setPendingAnswers] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    setBusy(true);
    converse([])
      .then((turn) => {
        setHistory([{ role: 'assistant', text: turn.message }]);
        if (turn.done) setPendingAnswers(turn.answers ?? {});
      })
      .catch(() => setError('Mo had trouble starting this conversation. Try reloading.'))
      .finally(() => setBusy(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setError(null);
    const next = [...history, { role: 'user' as const, text }];
    setHistory(next);
    setBusy(true);
    try {
      const turn = await converse(next);
      setHistory([...next, { role: 'assistant', text: turn.message }]);
      setPendingAnswers(turn.done ? (turn.answers ?? {}) : null);
    } catch {
      setError("That didn't go through. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!pendingAnswers) return;
    setBusy(true);
    setError(null);
    try {
      await submit(history, pendingAnswers);
      onSubmitted();
    } catch {
      setError("Couldn't submit. Try again.");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex h-full w-full max-w-lg flex-col gap-3 p-6">
      <div>
        <h1 className="text-lg font-semibold text-ink">{name}</h1>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      <div className="flex min-h-[240px] flex-1 flex-col gap-2 overflow-y-auto rounded-md border border-hair-soft p-3">
        {history.map((m, i) => (
          <div
            key={i}
            className={`max-w-[85%] rounded-lg px-3 py-1.5 text-sm ${
              m.role === 'assistant'
                ? 'self-start bg-surface-2 text-ink'
                : 'self-end bg-accent text-on-accent'
            }`}
          >
            {m.text}
          </div>
        ))}
        {busy ? <p className="self-start text-xs text-muted">Mo is typing…</p> : null}
        <div ref={bottomRef} />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-crit">
          {error}
        </p>
      ) : null}
      {pendingAnswers ? (
        <Button onClick={confirm} loading={busy}>
          Confirm and submit
        </Button>
      ) : (
        <form onSubmit={send} className="flex gap-2">
          <Input
            aria-label="Your answer"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your answer…"
            disabled={busy}
            maxLength={2000}
            className="flex-1"
          />
          <Button type="submit" disabled={busy || !input.trim()}>
            Send
          </Button>
        </form>
      )}
    </div>
  );
}
