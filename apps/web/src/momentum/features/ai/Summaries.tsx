import { X } from 'lucide-react';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { ApiError } from '@/lib/api/errors';
import { useMomentumConfig } from '@/lib/config';
import { MoText } from './MoThread';
import { useSummarize } from './queries';
import type { Citation } from './useMoRuns';

type Target = { target: 'task_thread'; task_id: string } | { target: 'inbox' };

/**
 * S3.4.1: "Summarize" (a task's thread) / "Catch me up" (unread inbox). The result shows as an
 * AI callout where it was asked for, with citation chips (comments by author and date, tasks as
 * links). Hidden while AI is off; failures say what happened and leave the page as it was.
 */
export function SummaryButton({ body, label }: { body: Target; label: string }) {
  const aiEnabled = useMomentumConfig().ai_enabled;
  const m = useSummarize();
  if (!aiEnabled) return null;
  return (
    <div className="contents">
      <Button size="sm" variant="ghost" loading={m.isPending} onClick={() => m.mutate(body)}>
        <MoMark size={13} /> {label}
      </Button>
      {m.data || m.isError ? (
        <div className="basis-full">
          <AICallout
            label={body.target === 'inbox' ? 'Mo’s catch-up' : 'Mo’s summary'}
            actions={<IconButton icon={X} label="Hide summary" size="icon-sm" onClick={() => m.reset()} />}
          >
            {m.data ? (
              <>
                <MoText text={m.data.summary} citations={m.data.citations as Citation[]} />
                <p className="mt-1.5 text-xs text-muted">
                  From {m.data.count} {body.target === 'inbox' ? 'unread notifications' : 'comments'}
                  {m.data.omitted ? ` (the ${m.data.omitted} oldest not included)` : ''}.
                </p>
              </>
            ) : (
              <p role="alert">{errorText(m.error)}</p>
            )}
          </AICallout>
        </div>
      ) : null}
    </div>
  );
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.problem.code === 'ai_unavailable') return 'Mo is unavailable right now. Try again shortly.';
    return e.problem.detail ?? e.problem.title ?? 'Something went wrong.';
  }
  return 'Something went wrong.';
}
