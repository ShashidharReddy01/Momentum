import { AlertTriangle, CheckCircle2, RefreshCw, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/dates';
import { basis, day, daysBetween, verdict } from './model';
import { useForecast, useRefreshForecast, type Forecast } from './queries';

const TONE = { ok: 'text-ok', warn: 'text-warn', crit: 'text-crit', none: 'text-muted' } as const;
const LEVEL = { none: 'No risk', low: 'Low', medium: 'Medium', high: 'High' } as const;
const LEVEL_BAR = { none: 'bg-hairline', low: 'bg-ok', medium: 'bg-warn', high: 'bg-crit' } as const;

/**
 * S6.5.3: the project's forecast on its overview. Not one guessed date but a range: the work is
 * done by P50 in half of 10,000 simulated futures (built from this project's own weekly pace),
 * by P80 in four out of five, by P95 in nearly all. The cone bar puts that range next to the due
 * date; the risk score says how worried to be and why, in words.
 */
export function ForecastCard({ projectId }: { projectId: string }) {
  const q = useForecast(projectId);
  const refresh = useRefreshForecast(projectId);
  const f = q.data;
  return (
    <section aria-label="Forecast" className="rounded-xl border border-hair-soft bg-surface p-4">
      <header className="mb-3 flex items-center gap-2">
        <Icon icon={TrendingUp} size={15} className="text-muted" aria-hidden />
        <h2 className="text-sm font-semibold">Forecast</h2>
        <span className="ml-auto text-xs text-muted">
          {f ? `Updated ${formatRelative(f.computed_at)}` : ''}
        </span>
        <Button
          size="sm"
          variant="text"
          onClick={() => refresh.mutate()}
          loading={refresh.isPending}
          aria-label="Refresh the forecast"
        >
          <Icon icon={RefreshCw} size={13} aria-hidden /> Refresh
        </Button>
      </header>
      {q.isPending ? (
        <Skeleton className="h-24" />
      ) : !f ? (
        <p className="text-sm text-muted">
          No forecast yet. Forecasts are made every night from the project&apos;s own pace; Refresh makes one
          now.
        </p>
      ) : f.status === 'done' ? (
        <p className="flex items-center gap-2 text-sm text-ink-2">
          <Icon icon={CheckCircle2} size={15} className="text-ok" aria-hidden /> Nothing left to forecast:
          every task is done.
        </p>
      ) : f.status === 'no_history' ? (
        <p className="text-sm text-muted">
          Not enough finished work to forecast yet. A forecast needs at least two weeks of this project&apos;s
          history with something completed in them.
        </p>
      ) : (
        <Body f={f} />
      )}
    </section>
  );
}

function Body({ f }: { f: Forecast }) {
  const v = verdict(f);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="text-2xl font-semibold">Likely done {day(f.p50!)}</p>
        <p className={cn('flex items-center gap-1 text-sm font-medium', TONE[v.tone])}>
          {v.tone === 'crit' || v.tone === 'warn' ? (
            <Icon icon={AlertTriangle} size={14} aria-hidden />
          ) : null}
          {v.text}
        </p>
      </div>
      <Cone f={f} />
      <Risk f={f} />
      <p className="text-xs text-muted">{basis(f)}</p>
    </div>
  );
}

/** Today → the far end: the P50-P95 band (P80 marked), and the due date as a line. */
function Cone({ f }: { f: Forecast }) {
  const today = f.as_of;
  const ends = [f.p95!, ...(f.due_on ? [f.due_on] : [])];
  const span = Math.max(7, ...ends.map((d) => daysBetween(today, d))) * 1.08;
  const at = (iso: string) => `${Math.min(100, Math.max(0, (daysBetween(today, iso) / span) * 100))}%`;
  const late = !!f.due_on && f.p80! > f.due_on;
  const marks = [
    { key: '50%', date: f.p50! },
    { key: '80%', date: f.p80! },
    { key: '95%', date: f.p95! },
  ];
  return (
    <figure
      aria-label={`Finish forecast: 50% by ${day(f.p50!)}, 80% by ${day(f.p80!)}, 95% by ${day(f.p95!)}${
        f.due_on ? `; due ${day(f.due_on)}` : ''
      }`}
    >
      <div className="relative h-7">
        <div className="absolute inset-x-0 top-3 h-1 rounded-full bg-surface-2" />
        <div
          className={cn('absolute top-2 h-3 rounded-full', late ? 'bg-crit-tint' : 'bg-info-tint')}
          style={{ left: at(f.p50!), width: `calc(${at(f.p95!)} - ${at(f.p50!)} + 4px)` }}
        />
        <div
          className={cn('absolute top-1 h-5 w-0.5 rounded-full', late ? 'bg-crit' : 'bg-info')}
          style={{ left: at(f.p80!) }}
          title={`80% likely done by ${day(f.p80!)}`}
        />
        <div
          className="absolute top-2.5 h-2 w-2 -translate-x-1/2 rounded-full bg-ink"
          style={{ left: at(f.p50!) }}
        />
        {f.due_on ? (
          <div
            className="absolute -top-0.5 h-8 border-l-2 border-dashed border-ink-2"
            style={{ left: at(f.due_on) }}
            title={`Due ${day(f.due_on)}`}
          />
        ) : null}
        <div className="absolute -top-0.5 h-8 border-l border-hairline" style={{ left: 0 }} />
      </div>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted">
        <span>From {day(today)}</span>
        {marks.map((m) => (
          <span key={m.key}>
            <span className="font-medium text-ink-2">{m.key}</span> by {day(m.date)}
          </span>
        ))}
        {f.due_on ? (
          <span>
            <span className="font-medium text-ink-2">Due</span> {day(f.due_on)}
          </span>
        ) : null}
      </figcaption>
    </figure>
  );
}

function Risk({ f }: { f: Forecast }) {
  const top = f.drivers.slice(0, 3);
  return (
    <div className="rounded-lg bg-canvas p-3">
      <div className="flex items-center gap-3">
        <span className="text-xs font-medium text-muted">Risk</span>
        <span className="text-lg font-semibold tabular-nums">{Math.round(f.risk_score)}</span>
        <span className="text-sm">{LEVEL[f.risk_level]}</span>
        <div className="h-1.5 flex-1 rounded-full bg-surface-2" aria-hidden>
          <div
            className={cn('h-1.5 rounded-full', LEVEL_BAR[f.risk_level])}
            style={{ width: `${Math.max(2, f.risk_score)}%` }}
          />
        </div>
      </div>
      {top.length ? (
        <ul aria-label="What drives the risk" className="mt-2 space-y-1 text-sm">
          {top.map((d) => (
            <li key={d.kind + d.text} className="flex gap-2">
              <span className="w-8 shrink-0 text-right text-xs tabular-nums text-muted">+{d.points}</span>
              <span>
                {d.text}
                {d.tasks.length ? (
                  <span className="text-muted">: {d.tasks.slice(0, 3).join(', ')}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-muted">No risk signals, and the forecast fits the due date.</p>
      )}
    </div>
  );
}
