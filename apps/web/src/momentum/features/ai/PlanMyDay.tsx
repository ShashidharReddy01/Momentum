import { X } from 'lucide-react';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { useMomentumConfig } from '@/lib/config';
import { errorText } from './errors';
import { MoText } from './MoThread';
import { PreviewCard } from './PreviewCard';
import { usePlanMyDay } from './queries';
import type { Citation } from './useMoRuns';

/**
 * S3.4.5 "Plan my day" on My Tasks: Mo's order for today (and what to move to Later) with its
 * reasons, as a PreviewCard; applying moves the tasks (one undo). Hidden while AI is off.
 */
export function PlanMyDayButton() {
  const aiEnabled = useMomentumConfig().ai_enabled;
  const m = usePlanMyDay();
  if (!aiEnabled) return null;
  return (
    <div className="contents">
      <Button size="sm" variant="ghost" loading={m.isPending} onClick={() => m.mutate()}>
        <MoMark size={13} /> Plan my day
      </Button>
      {m.data || m.isError ? (
        <div className="basis-full space-y-2">
          <AICallout
            label="Mo’s plan"
            actions={<IconButton icon={X} label="Hide plan" size="icon-sm" onClick={() => m.reset()} />}
          >
            {m.isError ? (
              <p role="alert">{errorText(m.error)}</p>
            ) : (
              <>
                {m.data!.rationale ? (
                  <MoText text={m.data!.rationale} citations={m.data!.citations as Citation[]} />
                ) : null}
                {m.data!.notes.length ? (
                  <ul
                    aria-label="Mo adjusted"
                    className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs text-muted"
                  >
                    {m.data!.notes.map((n) => (
                      <li key={n}>{n}</li>
                    ))}
                  </ul>
                ) : null}
                {!m.data!.action_id ? (
                  <p className="mt-1.5 text-sm">Your day already matches this plan.</p>
                ) : null}
              </>
            )}
          </AICallout>
          {m.data?.action_id ? <PreviewCard actionId={m.data.action_id} /> : null}
        </div>
      ) : null}
    </div>
  );
}
