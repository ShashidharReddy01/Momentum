import { useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/Button';
import {
  docText,
  useAnswerAsk,
  useInterpretReply,
  useMyAsks,
  type Ask,
  type Interpretation,
} from './platform';

/**
 * "Use this as the answer to <agent>'s question?" (spec §5.3): when an agent waits on me on this
 * task, a chip under the composer (on by default) reads my next comment as the answer. A certain
 * reading is applied ("Understood: …", with Change on the card); an uncertain one is shown here
 * to confirm with one click, never applied silently.
 */
export function useReplyAsAnswer(taskId: string): {
  ui: ReactNode;
  afterSend: (body: unknown) => void;
} {
  const asks = useMyAsks();
  const open = (asks.data ?? []).filter((a) => a.task_id === taskId && a.can_answer);
  const ask = open[0];
  const [use, setUse] = useState(true);
  const [pending, setPending] = useState<Interpretation | null>(null);
  const interpret = useInterpretReply();

  const afterSend = (body: unknown) => {
    if (!ask || !use) return;
    const text = docText(body);
    if (!text) return;
    interpret.mutate(
      { askId: ask.id, text },
      {
        onSuccess: (r) => {
          if (r.applied) toast.success(`Understood: ${r.understood}`);
          else setPending(r);
        },
      },
    );
  };

  const ui = (
    <>
      {pending ? <ConfirmReading reading={pending} onDone={() => setPending(null)} /> : null}
      {ask && !pending ? (
        <label className="mt-1.5 inline-flex items-center gap-1.5 rounded-full border border-amber/60 bg-amber-2/50 px-2 py-0.5 text-xs text-amber-ink">
          <input type="checkbox" checked={use} onChange={(e) => setUse(e.target.checked)} />
          Use this as the answer to {ask.agent.name}’s question “{ask.title}”
        </label>
      ) : null}
    </>
  );
  return { ui, afterSend };
}

function ConfirmReading({ reading, onDone }: { reading: Interpretation; onDone: () => void }) {
  const answer = useAnswerAsk(reading.ask.id);
  const ask: Ask = reading.ask;
  return (
    <section
      aria-label="Confirm the answer"
      className="mt-2 rounded-lg border border-dashed border-amber bg-amber-2/50 px-3 py-2 text-sm"
    >
      <p>
        Did you mean <strong>{reading.understood}</strong> as the answer to {ask.agent.name}’s question “
        {ask.title}”?
      </p>
      <div className="mt-1.5 flex gap-1.5">
        <Button
          size="sm"
          variant="primary"
          disabled={answer.isPending || reading.value == null}
          onClick={() =>
            answer.mutate(
              { value: reading.value, via: 'thread' },
              {
                onSuccess: () => {
                  toast.success(`Understood: ${reading.understood}`);
                  onDone();
                },
              },
            )
          }
        >
          Yes, use it
        </Button>
        <Button size="sm" variant="text" onClick={onDone}>
          No, I’ll answer on the card
        </Button>
      </div>
    </section>
  );
}
