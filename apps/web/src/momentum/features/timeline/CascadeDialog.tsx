import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { fromISODate } from '@/lib/dates';
import type { ReschedulePlan } from './queries';

const DATE = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
const fmt = (iso: string | null) => (iso ? DATE.format(fromISODate(iso)) : '—');
const range = (start: string | null, due: string | null) =>
  start && due && start !== due ? `${fmt(start)} – ${fmt(due)}` : fmt(due ?? start);

/**
 * "Move T-12 and the 4 tasks that wait on it?" (S6.1.2). Lists every dependent the server would
 * shift, with its new dates and how many days later, plus the ones it can't move (view-only, or
 * in projects the person can't see, which are only counted). Three ways out: move them all (one
 * undo), move only this task (the timeline then shows the conflicts), or cancel.
 */
export function CascadeDialog({
  plan,
  onAll,
  onOnly,
  onCancel,
}: {
  plan: ReschedulePlan | null;
  onAll: () => void;
  onOnly: () => void;
  onCancel: () => void;
}) {
  const n = plan?.shifted.length ?? 0;
  const key = plan?.moved.key ?? '';
  return (
    <Dialog
      open={!!plan}
      onOpenChange={(o) => !o && onCancel()}
      title={`Move ${key} and ${n} ${n === 1 ? 'task that waits' : 'tasks that wait'} on it?`}
      description="Nothing starts before the work it depends on is due."
    >
      {plan ? (
        <div className="px-5 py-4">
          <p className="text-sm">
            <span className="font-mono text-xs text-muted-2">{plan.moved.key}</span> {plan.moved.title}:{' '}
            <span className="text-muted line-through">
              {range(plan.moved.from_start, plan.moved.from_due)}
            </span>{' '}
            → <span className="font-medium">{range(plan.moved.to_start, plan.moved.to_due)}</span>
          </p>
          <ul
            aria-label="Tasks that would move"
            className="mt-3 max-h-72 divide-y divide-hair-soft overflow-auto"
          >
            {plan.shifted.map((c) => (
              <li key={c.id} className="flex items-baseline gap-2 py-1.5 text-sm">
                <span className="shrink-0 font-mono text-xs text-muted-2">{c.key}</span>
                <span className="min-w-0 flex-1 truncate">{c.title}</span>
                <span className="shrink-0 tabular-nums text-muted">{range(c.to_start, c.to_due)}</span>
                <span className="w-16 shrink-0 text-right text-xs tabular-nums text-warn">
                  +{c.shift_days} {c.shift_days === 1 ? 'day' : 'days'}
                </span>
              </li>
            ))}
          </ul>
          {plan.skipped.length || plan.hidden_skipped ? (
            <p role="note" className="mt-3 rounded-md bg-warn-tint px-3 py-2 text-sm text-warn">
              {plan.skipped.length
                ? `You can't edit ${plan.skipped.map((s) => s.key).join(', ')}, so ${
                    plan.skipped.length === 1 ? 'it stays' : 'they stay'
                  } put. `
                : ''}
              {plan.hidden_skipped
                ? `${plan.hidden_skipped} more ${
                    plan.hidden_skipped === 1 ? 'task' : 'tasks'
                  } in projects you can't see also wait on this.`
                : ''}
            </p>
          ) : null}
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="text" onClick={onCancel}>
              Cancel
            </Button>
            <Button variant="ghost" onClick={onOnly}>
              Only {plan.moved.key}
            </Button>
            <Button variant="primary" onClick={onAll}>
              Move all {n + 1}
            </Button>
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}
