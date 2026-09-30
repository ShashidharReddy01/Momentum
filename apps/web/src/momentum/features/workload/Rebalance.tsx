import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, CalendarClock, CheckCircle2, GitBranch, X } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { useAiActionMutations } from '@/features/ai';
import { hours } from '@/features/tasks';
import type { components } from '@/lib/api/schema';
import { cn } from '@/lib/cn';
import { fromISODate } from '@/lib/dates';
import { useApi } from '@/providers/api';
import { toneOf, type Tone } from './grid';

export type Rebalance = components['schemas']['RebalanceOut'];
export type RebalanceMove = components['schemas']['RebalanceMoveOut'];
/** person → week → the load before and after the suggested moves (changed cells only). */
export type LoadPreview = Map<string, Map<string, { before: number; after: number }>>;

const day = (iso: string) =>
  fromISODate(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

export function useRebalance() {
  const api = useApi();
  return useMutation({
    mutationFn: async (v: { start: string; weeks: number; projectId: string | null }) =>
      (
        await api.POST('/api/v1/ai/workload/rebalance', {
          body: { start: v.start, weeks: v.weeks, ...(v.projectId ? { project_id: v.projectId } : {}) },
        })
      ).data!,
  });
}

export function previewOf(r: Rebalance): LoadPreview {
  const out: LoadPreview = new Map();
  for (const p of r.people) {
    for (const w of p.weeks) {
      if (w.before_minutes === w.after_minutes) continue;
      const row = out.get(p.user_id) ?? new Map();
      row.set(w.week_start, { before: w.before_minutes, after: w.after_minutes });
      out.set(p.user_id, row);
    }
  }
  return out;
}

const INK: Record<Tone, string> = {
  idle: 'text-muted',
  ok: 'text-ok',
  warn: 'text-warn',
  crit: 'text-crit',
  away: 'text-muted',
};
const FILL: Record<Tone, string> = {
  idle: 'bg-hair-soft',
  ok: 'bg-ok',
  warn: 'bg-warn',
  crit: 'bg-crit',
  away: 'bg-hair-soft',
};

/**
 * ✦ Suggest rebalance (S6.4.2): the moves a greedy heuristic found (code), Mo's explanation, the load
 * before → after for everyone it touches, and one Apply for all of it (one undo). While it's open
 * the grid shows the "after" loads.
 */
export function RebalancePanel({
  result,
  onClose,
  onRetry,
  retrying,
}: {
  result: Rebalance;
  onClose: () => void;
  onRetry: () => void;
  retrying: boolean;
}) {
  return (
    <aside
      aria-label="Suggested rebalance"
      className="flex w-full shrink-0 flex-col border-l border-hairline bg-surface md:w-[400px]"
    >
      <header className="flex items-center gap-2 border-b border-hair-soft px-4 py-3">
        <MoMark size={15} />
        <h2 className="mr-auto text-sm font-semibold">Suggested rebalance</h2>
        <IconButton icon={X} label="Close the suggestion" size="icon-sm" onClick={onClose} />
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        <AICallout label="Mo suggests">
          <p className="font-medium text-ink">{result.headline}</p>
          {result.summary ? <p className="mt-1">{result.summary}</p> : null}
          {result.moves.length && !result.ai ? (
            <p className="mt-1.5 text-xs text-muted">
              Explained from the numbers (the model’s text wasn’t used).
            </p>
          ) : null}
        </AICallout>
        {result.moves.length ? <LoadChanges result={result} /> : null}
        {result.moves.length ? (
          <section aria-labelledby="rebalance-moves">
            <h3
              id="rebalance-moves"
              className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted"
            >
              {result.moves.length} change{result.moves.length === 1 ? '' : 's'}
            </h3>
            <ol className="space-y-2">
              {result.moves.map((m) => (
                <MoveRow key={m.task_id} move={m} />
              ))}
            </ol>
          </section>
        ) : null}
        {result.unresolved.length ? <StillOver result={result} /> : null}
      </div>
      {result.action_id ? (
        <ApplyBar
          actionId={result.action_id}
          count={result.moves.length}
          onDone={onClose}
          onRetry={onRetry}
          retrying={retrying}
        />
      ) : null}
    </aside>
  );
}

function LoadChanges({ result }: { result: Rebalance }) {
  const rows = result.people.flatMap((p) =>
    p.weeks
      .filter((w) => w.before_minutes !== w.after_minutes)
      .map((w) => ({ person: p.name, key: `${p.user_id}:${w.week_start}`, ...w })),
  );
  return (
    <section aria-labelledby="rebalance-load">
      <h3 id="rebalance-load" className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
        Load, before → after
      </h3>
      <ul className="space-y-2">
        {rows.map((r) => {
          const before = toneOf(r.before_minutes, r.capacity_minutes);
          const after = toneOf(r.after_minutes, r.capacity_minutes);
          const scale = Math.max(r.before_minutes, r.after_minutes, r.capacity_minutes) || 1;
          return (
            <li key={r.key} className="text-[13px]">
              <div className="flex items-baseline gap-2">
                <span className="min-w-0 flex-1 truncate">
                  <span className="font-medium">{r.person}</span>
                  <span className="text-muted"> · week of {day(r.week_start)}</span>
                </span>
                <span className="tabular whitespace-nowrap text-xs">
                  <span className={INK[before]}>{hours(r.before_minutes)}</span>
                  <Icon icon={ArrowRight} size={11} className="mx-0.5 inline text-muted-2" />
                  <span className={cn('font-semibold', INK[after])}>{hours(r.after_minutes)}</span>
                  <span className="text-muted"> / {hours(r.capacity_minutes)}</span>
                </span>
              </div>
              {/* two thin bars on one scale, with the capacity line across both */}
              <div className="relative mt-1 space-y-0.5" aria-hidden>
                <div className="h-1 rounded-full bg-hair-soft">
                  <div
                    className={cn('h-full rounded-full opacity-40', FILL[before])}
                    style={{ width: `${(r.before_minutes / scale) * 100}%` }}
                  />
                </div>
                <div className="h-1.5 rounded-full bg-hair-soft">
                  <div
                    className={cn('h-full rounded-full', FILL[after])}
                    style={{ width: `${(r.after_minutes / scale) * 100}%` }}
                  />
                </div>
                <div
                  className="absolute -inset-y-0.5 w-px bg-ink-2"
                  style={{ left: `${(r.capacity_minutes / scale) * 100}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function MoveRow({ move: m }: { move: RebalanceMove }) {
  return (
    <li className="rounded-lg border border-hair-soft bg-surface px-3 py-2">
      <div className="flex items-baseline gap-2 text-[13px]">
        <span className="font-mono text-xs text-muted">{m.key}</span>
        <span className="min-w-0 flex-1 truncate font-medium" title={m.title}>
          {m.title}
        </span>
        <span className="tabular text-xs text-muted">{hours(m.estimate_minutes)}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
        {m.kind === 'reassign' ? (
          <span className="inline-flex items-center gap-1 rounded bg-surface-2 px-1.5 py-0.5">
            {m.from_person.name}
            <Icon icon={ArrowRight} size={11} />
            <span className="font-semibold">{m.to_person?.name}</span>
          </span>
        ) : m.kind === 'start_later' ? (
          <span className="inline-flex items-center gap-1 rounded bg-surface-2 px-1.5 py-0.5">
            <Icon icon={CalendarClock} size={11} /> Starts {day(m.to_start!)} · due date unchanged
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded bg-warn-tint px-1.5 py-0.5 text-warn">
            <Icon icon={CalendarClock} size={11} />
            {m.weeks_later === 1 ? 'A week later' : `${m.weeks_later} weeks later`} · due {day(m.from_due)} →{' '}
            {day(m.to_due)}
          </span>
        )}
        {m.shifted.length ? (
          <span
            className="inline-flex items-center gap-1 text-muted"
            title={m.shifted.map((s) => `${s.key} ${s.title}`).join('\n')}
          >
            <Icon icon={GitBranch} size={11} /> {m.shifted.length} dependent
            {m.shifted.length === 1 ? '' : 's'} follow
          </span>
        ) : null}
        {m.past_project_due ? (
          <span className="inline-flex items-center gap-1 text-crit">
            <Icon icon={AlertTriangle} size={11} /> after the project’s due date
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-xs text-muted">
        {m.project_name} · {m.why}
      </p>
    </li>
  );
}

function StillOver({ result }: { result: Rebalance }) {
  return (
    <section aria-labelledby="rebalance-still-over" className="rounded-lg bg-crit-tint/60 px-3 py-2">
      <h3 id="rebalance-still-over" className="mb-1 text-xs font-semibold text-crit">
        Still over capacity
      </h3>
      <ul className="space-y-0.5 text-xs text-ink-2">
        {result.unresolved.map((u) => (
          <li key={`${u.user_id}:${u.week_start}`}>
            {u.name}, week of {day(u.week_start)}: {hours(u.over_minutes)} over.{' '}
            {u.reason === 'nothing_movable'
              ? 'Nothing there you can move (only estimated work in projects you edit moves).'
              : 'Nobody with access has room, and no date move fits.'}
          </li>
        ))}
      </ul>
      {result.limited ? (
        <p className="mt-1 text-xs text-muted">
          Stopped at the most changes suggested at once; apply these, then ask again.
        </p>
      ) : null}
    </section>
  );
}

function ApplyBar({
  actionId,
  count,
  onDone,
  onRetry,
  retrying,
}: {
  actionId: string;
  count: number;
  onDone: () => void;
  onRetry: () => void;
  retrying: boolean;
}) {
  const m = useAiActionMutations(actionId);
  const [stale, setStale] = useState(false);
  const apply = () =>
    m.apply.mutate(false, {
      onSuccess: (r) => {
        if (r.outcome === 'repreviewed') return setStale(true);
        if (r.outcome !== 'applied') {
          toast.error(`Couldn’t apply the rebalance${r.data.error ? `: ${r.data.error}` : ''}`);
          return;
        }
        toast.success(`Rebalanced: ${count} change${count === 1 ? '' : 's'}`, {
          icon: <Icon icon={CheckCircle2} size={16} />,
          duration: 10_000,
          action: {
            label: 'Undo',
            onClick: () => m.undo.mutate(undefined, { onSuccess: () => toast('Undone') }),
          },
        });
        onDone();
      },
    });
  return (
    <footer className="border-t border-hair-soft px-4 py-3">
      {stale ? (
        <div role="status" className="mb-2 rounded bg-warn-tint px-2 py-1.5 text-[13px] text-warn">
          Something changed since this suggestion.{' '}
          <button type="button" className="font-medium underline" onClick={onRetry} disabled={retrying}>
            Suggest again
          </button>
        </div>
      ) : null}
      <div className="flex items-center gap-2">
        <Button variant="ai" loading={m.apply.isPending} onClick={apply} disabled={stale}>
          Apply {count} change{count === 1 ? '' : 's'}
        </Button>
        <Button
          variant="text"
          loading={m.reject.isPending}
          onClick={() => m.reject.mutate(undefined, { onSuccess: onDone })}
        >
          Dismiss
        </Button>
        <span className="ml-auto text-xs text-muted">One undo for all of it</span>
      </div>
    </footer>
  );
}
