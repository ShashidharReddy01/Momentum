import { Loader2, X } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { toast } from 'sonner';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { describeStep, PreviewCard, useAiActionMutations, useMoRuns, type MoRun } from '@/features/ai';
import { useUi } from '@/stores/ui';

/**
 * Right-side assistant panel (⌘J). S3.2.2: runs of natural-language commands sent from ⌘K or
 * typed here — the tools Mo used, its reply, the proposed change as a PreviewCard, or a question
 * with the candidates to choose from. Ask Mo chat (S3.3.1) extends this panel.
 */
export function AskMoPanel() {
  const open = useUi((s) => s.askMoOpen);
  const setOpen = useUi((s) => s.setAskMoOpen);
  const moRequest = useUi((s) => s.moRequest);
  const takeMoRequest = useUi((s) => s.takeMoRequest);
  const openPalette = useUi((s) => s.openPalette);
  const { runs, run } = useMoRuns();
  const [draft, setDraft] = useState('');
  const end = useRef<HTMLDivElement>(null);

  // a request sent from elsewhere (⌘K) starts a run here
  useEffect(() => {
    if (!moRequest) return;
    const req = takeMoRequest();
    if (req) void run(req.text);
  }, [moRequest, takeMoRequest, run]);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' });
  }, [runs]);

  if (!open) return null;
  const busy = runs.some((r) => r.status === 'running');
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    void run(text);
  };

  return (
    <aside
      aria-label="Ask Mo"
      className="flex h-full w-[var(--askmo-w)] shrink-0 flex-col border-l border-hair-soft bg-surface shadow-pane max-md:fixed max-md:inset-0 max-md:z-30 max-md:w-full max-md:border-l-0"
    >
      <header className="flex h-[var(--topbar-h)] items-center gap-2 border-b border-hair-soft px-4">
        <MoMark size={16} />
        <h2 className="flex-1 font-medium">Ask Mo</h2>
        <IconButton
          icon={X}
          label="Close Ask Mo"
          shortcut="mod+j"
          size="icon-sm"
          onClick={() => setOpen(false)}
        />
      </header>
      <div className="flex-1 space-y-5 overflow-auto p-4">
        {runs.length === 0 ? (
          <AICallout>
            <p className="font-medium text-ink">Hi, I&apos;m Mo.</p>
            <p className="mt-1">
              Tell me what to change, like “assign all overdue tasks in Website Revamp to Ana”. I&apos;ll show
              you the changes first; nothing happens until you apply them.
            </p>
          </AICallout>
        ) : null}
        {runs.map((r) => (
          <RunView
            key={r.id}
            run={r}
            onEdit={() => openPalette(r.text)}
            onChoose={(choice) => void run(`${r.text} (I mean ${choice})`)}
          />
        ))}
        <div ref={end} />
      </div>
      <form onSubmit={submit} className="flex gap-2 border-t border-hair-soft p-3">
        <input
          aria-label="Message Mo"
          placeholder="Tell Mo what to change…"
          value={draft}
          maxLength={1000}
          onChange={(e) => setDraft(e.target.value)}
          className="h-9 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-3 text-sm outline-none placeholder:text-muted-2 focus:border-focus"
        />
        <Button type="submit" variant="ai" size="md" disabled={!draft.trim() || busy}>
          Send
        </Button>
      </form>
    </aside>
  );
}

function RunView({
  run,
  onEdit,
  onChoose,
}: {
  run: MoRun;
  onEdit: () => void;
  onChoose: (choice: string) => void;
}) {
  return (
    <section aria-label={`Request: ${run.text}`} className="space-y-2">
      <p className="ml-8 rounded-lg bg-surface-2 px-3 py-2 text-sm text-ink">{run.text}</p>
      {run.steps.length ? (
        <p className="text-xs text-muted" aria-label="What Mo did">
          {run.steps.map((s) => describeStep(s) + (s.ok === false ? ' (failed)' : '')).join(' · ')}
        </p>
      ) : null}
      {run.status === 'running' && !run.reply ? (
        <p role="status" className="flex items-center gap-1.5 text-sm text-muted">
          <Icon icon={Loader2} className="animate-spin" /> Mo is working…
        </p>
      ) : null}
      {run.reply && !run.clarify ? (
        <div className="flex gap-2 text-sm text-ink-2">
          <MoMark size={14} />
          <p className="flex-1">{run.reply}</p>
        </div>
      ) : null}
      {run.clarify ? (
        <AICallout label="Mo asks">
          <p>{run.clarify.question}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {run.clarify.candidates.map((c) => {
              const label = c.key ? `${c.key} ${c.title ?? ''}`.trim() : (c.name ?? '');
              return (
                <Button
                  key={label}
                  size="sm"
                  variant="ghost"
                  onClick={() => onChoose(c.key ?? c.name ?? label)}
                >
                  {label}
                  {c.project ? <span className="text-muted"> · {c.project}</span> : null}
                </Button>
              );
            })}
          </div>
        </AICallout>
      ) : null}
      {run.actionId ? (
        run.autoApplied ? (
          <AutoApplied actionId={run.actionId} />
        ) : (
          <PreviewCard actionId={run.actionId} onEdit={onEdit} />
        )
      ) : null}
      {run.error ? (
        <p role="alert" className="text-sm text-crit">
          {run.error}
        </p>
      ) : null}
    </section>
  );
}

/** A low-risk change applied without asking (the user's setting): still shown, with Undo. */
function AutoApplied({ actionId }: { actionId: string }) {
  const m = useAiActionMutations(actionId);
  const [undone, setUndone] = useState(false);
  return (
    <div className="space-y-2">
      <PreviewCard actionId={actionId} />
      {!undone ? (
        <p className="flex items-center gap-2 text-[13px] text-muted">
          Applied automatically (low risk).
          <Button
            size="sm"
            variant="text"
            loading={m.undo.isPending}
            onClick={() =>
              m.undo.mutate(undefined, {
                onSuccess: () => {
                  setUndone(true);
                  toast('Undone');
                },
              })
            }
          >
            Undo
          </Button>
        </p>
      ) : null}
    </div>
  );
}
