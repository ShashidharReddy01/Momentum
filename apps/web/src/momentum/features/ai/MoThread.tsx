import { Loader2, ThumbsDown, ThumbsUp } from 'lucide-react';
import { Fragment, useState, type FormEvent, type ReactNode } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { cn } from '@/lib/cn';
import { PreviewCard } from './PreviewCard';
import { useAiActionMutations, useFeedback } from './queries';
import { describeStep, type Citation, type MoRun } from './useMoRuns';

/** Runs of Mo (commands and chat questions): shared by the Ask Mo panel and the `/ask` page. */
export function MoThread({
  runs,
  onEdit,
  onChoose,
  onRated,
}: {
  runs: MoRun[];
  onEdit?: (run: MoRun) => void;
  onChoose: (run: MoRun, choice: string) => void;
  onRated: (run: MoRun, rating: -1 | 1) => void;
}) {
  return (
    <>
      {runs.map((r) => (
        <RunView
          key={r.id}
          run={r}
          onEdit={onEdit && r.kind === 'command' ? () => onEdit(r) : undefined}
          onChoose={(choice) => onChoose(r, choice)}
          onRated={(rating) => onRated(r, rating)}
        />
      ))}
    </>
  );
}

function RunView({
  run,
  onEdit,
  onChoose,
  onRated,
}: {
  run: MoRun;
  onEdit?: () => void;
  onChoose: (choice: string) => void;
  onRated: (rating: -1 | 1) => void;
}) {
  const label = run.kind === 'chat' ? 'Question' : 'Request';
  return (
    <section aria-label={`${label}: ${run.text}`} className="space-y-2">
      <p className="ml-8 whitespace-pre-wrap rounded-lg bg-surface-2 px-3 py-2 text-sm text-ink">
        {run.text}
      </p>
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
        <div className="flex gap-2 text-sm text-ink-2" aria-label="Mo's answer (AI)" role="group">
          <MoMark size={14} />
          <div className="min-w-0 flex-1">
            <MoText text={run.reply} citations={run.citations} />
            {run.kind === 'chat' && run.status === 'done' ? (
              <div className="mt-1.5 flex items-center gap-1">
                {run.grounded === false ? (
                  <span className="mr-1 text-xs text-muted">No sources from your workspace cited.</span>
                ) : null}
                {run.messageId ? <Rate run={run} onRated={onRated} /> : null}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
      {run.clarify ? (
        <AICallout label="Mo asks">
          <p>{run.clarify.question}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {run.clarify.candidates.map((c) => {
              const text = c.key ? `${c.key} ${c.title ?? ''}`.trim() : (c.name ?? '');
              return (
                <Button
                  key={text}
                  size="sm"
                  variant="ghost"
                  onClick={() => onChoose(c.key ?? c.name ?? text)}
                >
                  {text}
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

function Rate({ run, onRated }: { run: MoRun; onRated: (rating: -1 | 1) => void }) {
  const feedback = useFeedback();
  const send = (rating: -1 | 1) =>
    feedback.mutate(
      { target_type: 'ai_message', target_id: run.messageId!, rating },
      { onSuccess: () => onRated(rating) },
    );
  return (
    <>
      <IconButton
        icon={ThumbsUp}
        size="icon-sm"
        label="Good answer"
        aria-pressed={run.rating === 1}
        className={cn(run.rating === 1 && 'text-ink')}
        onClick={() => send(1)}
      />
      <IconButton
        icon={ThumbsDown}
        size="icon-sm"
        label="Bad answer"
        aria-pressed={run.rating === -1}
        className={cn(run.rating === -1 && 'text-ink')}
        onClick={() => send(-1)}
      />
    </>
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

const INLINE = /(\[T-\d+\]|\[C\d+\]|\[P:[^\]\n]+\]|\*\*[^*\n]+\*\*)/g;

/**
 * Mo's text as a small safe subset of Markdown (paragraphs, `- ` bullets, **bold**), built as
 * React nodes (never HTML). `[T-12]` / `[P:Name]` become links only when the server resolved
 * them for this user; anything else stays plain text marked as unverified.
 */
export function MoText({ text, citations }: { text: string; citations: Citation[] }) {
  const byRef = new Map(citations.map((c) => [c.ref, c]));
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={blocks.length} className="list-disc space-y-0.5 pl-5">
        {bullets.map((b, i) => (
          <li key={i}>{inline(b, byRef)}</li>
        ))}
      </ul>,
    );
    bullets = [];
  };
  for (const line of text.split('\n')) {
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    if (bullet) {
      bullets.push(bullet[1]!);
      continue;
    }
    flush();
    if (line.trim())
      blocks.push(
        <p key={blocks.length} className="whitespace-pre-wrap">
          {inline(line, byRef)}
        </p>,
      );
  }
  flush();
  return <div className="space-y-1.5">{blocks}</div>;
}

function inline(line: string, byRef: Map<string, Citation>): ReactNode {
  return line.split(INLINE).map((part, i) => {
    if (i % 2 === 0) return <Fragment key={i}>{part}</Fragment>;
    if (part.startsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>;
    return <Cite key={i} refText={part} citation={byRef.get(part)} />;
  });
}

function Cite({ refText, citation }: { refText: string; citation?: Citation }) {
  if (!citation) return <>{refText}</>; // not resolved (yet): plain text while streaming
  if (citation.type === 'comment') {
    const when = citation.created_at
      ? new Date(citation.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
      : '';
    return citation.valid ? (
      <span
        aria-label={`Comment by ${citation.title ?? 'unknown'}${when ? `, ${when}` : ''}`}
        className="mx-0.5 inline-flex items-center rounded border border-hair-soft bg-surface-2 px-1 text-[12px] text-ink-2"
      >
        {citation.title?.split(' ')[0] ?? 'Comment'}
        {when ? ` · ${when}` : ''}
      </span>
    ) : (
      <span title="Mo cited a comment that isn't in this thread" className="text-muted">
        {refText}
      </span>
    );
  }
  const shown = citation.type === 'task' ? (citation.key ?? refText) : (citation.title ?? refText);
  if (!citation.valid || !citation.id)
    return (
      <span title="Mo cited this, but it isn't something you can open" className="text-muted">
        {refText}
      </span>
    );
  const to = citation.type === 'task' ? `/task/${citation.id}` : `/projects/${citation.id}`;
  return (
    <Link
      to={to}
      title={citation.title ?? undefined}
      aria-label={citation.type === 'task' ? `${shown} ${citation.title ?? ''}`.trim() : `Project ${shown}`}
      className="mx-0.5 inline-flex items-center rounded border border-hair-soft bg-surface-2 px-1 font-mono text-[12px] text-ink hover:border-hairline"
    >
      {shown}
    </Link>
  );
}

/** The message box under a thread. */
export function MoComposer({
  onSend,
  busy,
  placeholder = 'Ask Mo anything about your work…',
}: {
  onSend: (text: string) => void;
  busy: boolean;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState('');
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    onSend(text);
  };
  return (
    <form onSubmit={submit} className="flex gap-2 border-t border-hair-soft p-3">
      <input
        aria-label="Message Mo"
        placeholder={placeholder}
        value={draft}
        maxLength={4000}
        onChange={(e) => setDraft(e.target.value)}
        className="h-9 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-3 text-sm outline-none placeholder:text-muted-2 focus:border-focus"
      />
      <Button type="submit" variant="ai" size="md" disabled={!draft.trim() || busy}>
        Send
      </Button>
    </form>
  );
}
