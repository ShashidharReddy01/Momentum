import { X } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { useMomentumConfig } from '@/lib/config';
import { PreviewCard } from './PreviewCard';
import { useBreakdown } from './queries';
import { errorText } from './Summaries';

/**
 * S3.4.2 "Break down": Mo proposes 3–10 subtasks (optionally guided: "split by week"), shown as a
 * PreviewCard to apply or dismiss, plus notes on anything the server corrected (people who
 * aren't on the project, dates out of range, duplicates). Only for people who can add subtasks;
 * hidden while AI is off.
 */
export function BreakDownButton({ taskId }: { taskId: string }) {
  const aiEnabled = useMomentumConfig().ai_enabled;
  const m = useBreakdown(taskId);
  const [asking, setAsking] = useState(false);
  const [hint, setHint] = useState('');
  if (!aiEnabled) return null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate(hint.trim() || null);
  };
  return (
    <div className="contents">
      <Button size="sm" variant="ghost" onClick={() => setAsking((a) => !a)} aria-expanded={asking}>
        <MoMark size={13} /> Break down
      </Button>
      {asking ? (
        <div className="basis-full space-y-2">
          {!m.data ? (
            <form onSubmit={submit} className="flex gap-2">
              <input
                aria-label="Guidance for Mo (optional)"
                placeholder="Optional: how to split it (by week, by person…)"
                value={hint}
                maxLength={500}
                onChange={(e) => setHint(e.target.value)}
                className="h-8 min-w-0 flex-1 rounded-md border border-hairline bg-surface px-2 text-sm outline-none placeholder:text-muted-2 focus:border-focus"
              />
              <Button type="submit" size="sm" variant="ai" loading={m.isPending}>
                Suggest subtasks
              </Button>
              <IconButton icon={X} label="Cancel" size="icon-sm" onClick={() => setAsking(false)} />
            </form>
          ) : null}
          {m.isError ? (
            <p role="alert" className="text-sm text-crit">
              {errorText(m.error)}
            </p>
          ) : null}
          {m.data ? (
            <>
              {m.data.notes.length ? (
                <ul aria-label="Mo adjusted" className="list-disc space-y-0.5 pl-5 text-xs text-muted">
                  {m.data.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              ) : null}
              <PreviewCard
                actionId={m.data.action_id}
                onEdit={() => {
                  m.reset();
                }}
              />
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
