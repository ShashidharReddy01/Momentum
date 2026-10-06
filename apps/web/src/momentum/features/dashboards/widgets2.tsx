import { AlertTriangle, ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import type { ReactNode } from 'react';
import { Icon } from '@/components/ui/Icon';
import { cn } from '@/lib/cn';
import { formatValue, OTHER_COLOR, tokenColor, unitOf } from './model';
import type { QueryResult, StageStat, TimelineItem } from './queries';
import type { Mark, WidgetItem } from './WidgetCard';

/**
 * Phase 7.5 (spec §7.2): the widget kinds v2 specs draw. Plain HTML bars rather than a chart
 * library: each mark is a button (keyboard and screen reader reachable) that drills into what
 * it counts, and every number is written next to its bar, so nothing relies on colour alone.
 */

function Quiet({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

const BAR_BTN =
  'w-full rounded-md px-1 py-1 text-left hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-focus';

// ---------- KPI: a number, the period before, a target ----------

/** "▲ 20% vs the previous period" (or "▼", or "same as"); a zero before has no percentage. */
export function deltaText(value: number, previous: number): { dir: -1 | 0 | 1; text: string } {
  if (value === previous) return { dir: 0, text: 'same as the period before' };
  const dir = value > previous ? 1 : -1;
  if (!previous) return { dir, text: `up from 0 the period before` };
  const pct = Math.round((Math.abs(value - previous) / previous) * 100);
  return { dir, text: `${pct}% ${dir > 0 ? 'up on' : 'down on'} the period before` };
}

export function Kpi({ data, onDrill }: { data: QueryResult; onDrill: (m: Mark) => void }) {
  const value = data.value ?? null;
  if (value === null) return <Quiet>No number yet. {data.description}.</Quiet>;
  const prev = data.previous ?? null;
  const target = data.target ?? null;
  const delta = prev !== null ? deltaText(value, prev) : null;
  const ring = target ? Math.min(1, value / target) : null;
  return (
    <button
      type="button"
      onClick={() => onDrill({})}
      title={`${data.description}. Show what this counts`}
      className="-mx-1 flex w-[calc(100%+8px)] items-center gap-3 rounded-md px-1 text-left hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-focus"
    >
      <span className="flex min-w-0 flex-1 flex-col items-start">
        <span className="text-[34px] leading-tight font-semibold tabular-nums">
          {formatValue(data, value)}
        </span>
        <span className="text-xs text-muted">{unitOf(data, value)}</span>
        {delta ? (
          <span
            className={cn(
              'mt-0.5 flex items-center gap-1 text-xs',
              delta.dir > 0 ? 'text-ok' : delta.dir < 0 ? 'text-warn' : 'text-muted',
            )}
          >
            <Icon
              icon={delta.dir > 0 ? ArrowUpRight : delta.dir < 0 ? ArrowDownRight : Minus}
              size={12}
              aria-hidden
            />
            {delta.text} ({formatValue(data, prev!)})
          </span>
        ) : null}
      </span>
      {ring !== null ? (
        <span
          className="relative shrink-0"
          title={`${Math.round(ring * 100)}% of the ${formatValue(data, target!)} target`}
        >
          <svg width="44" height="44" viewBox="0 0 44 44" aria-hidden>
            <circle cx="22" cy="22" r="18" fill="none" stroke="var(--hair-soft)" strokeWidth="5" />
            <circle
              cx="22"
              cy="22"
              r="18"
              fill="none"
              stroke="var(--chart-1)"
              strokeWidth="5"
              strokeDasharray={`${ring * 113.1} 113.1`}
              transform="rotate(-90 22 22)"
            />
          </svg>
          <span className="sr-only">{Math.round(ring * 100)}% of target</span>
        </span>
      ) : null}
    </button>
  );
}

// ---------- stacked bar ----------

export function StackedBars({
  item,
  data,
  onDrill,
}: {
  item: WidgetItem;
  data: QueryResult;
  onDrill: (m: Mark) => void;
}) {
  const groups = data.groups ?? [];
  const stacks = data.stacks ?? [];
  if (!groups.length) return <Quiet>Nothing matches yet. {data.description}.</Quiet>;
  const max = Math.max(1, ...groups.map((g) => g.value));
  const colors = stacks.map(
    (s, i) => tokenColor(s.color) ?? (s.key === 'none' ? OTHER_COLOR : `var(--chart-${(i % 8) + 1})`),
  );
  return (
    <div>
      <ul className="space-y-1.5">
        {groups.map((g, gi) => (
          <li key={g.key}>
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate">{g.label}</span>
              <span className="tabular-nums text-muted">{formatValue(data, g.value)}</span>
            </div>
            <div
              className="mt-0.5 flex h-3 overflow-hidden rounded-sm bg-surface-2"
              style={{ width: `${Math.max(4, (g.value / max) * 100)}%` }}
            >
              {stacks.map((s, si) => {
                const v = s.values[gi] ?? 0;
                if (!v) return null;
                return (
                  <button
                    key={s.key}
                    type="button"
                    aria-label={`${g.label}, ${s.label}: ${formatValue(data, v)}`}
                    title={`${s.label}: ${formatValue(data, v)}`}
                    onClick={() => onDrill({ key: g.key, splitKey: s.key, label: `${g.label} · ${s.label}` })}
                    className="h-full focus-visible:outline-2 focus-visible:outline-focus"
                    style={{ width: `${(v / g.value) * 100}%`, background: colors[si] }}
                  />
                );
              })}
            </div>
          </li>
        ))}
      </ul>
      <ul
        className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted"
        aria-label={`${item.title}: legend`}
      >
        {stacks.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: colors[i] }} />
            {s.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------- projects table ----------

const COLUMN_LABELS: Record<string, string> = {
  name: 'Project',
  owner: 'Owner',
  status: 'Status',
  stage: 'Stage',
  progress: 'Progress',
  open: 'Open',
  overdue: 'Overdue',
  blocked: 'Blocked',
  waiting_on_customer: 'Waiting on customer',
  next_milestone: 'Next milestone',
  target_date: 'Target',
  forecast_date: 'Forecast',
  slip_days: 'Slip',
  stage_age_days: 'In stage',
  latest_update: 'Latest update',
};
const STATUS_WORDS: Record<string, string> = {
  on_track: 'On track',
  at_risk: 'At risk',
  off_track: 'Off track',
  on_hold: 'On hold',
  complete: 'Complete',
};

function cellText(col: string, v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (col === 'progress' && typeof v === 'number') return `${Math.round(v * 100)}%`;
  if (col === 'status' && typeof v === 'string') return STATUS_WORDS[v] ?? v;
  if ((col === 'slip_days' || col === 'stage_age_days') && typeof v === 'number') return `${v}d`;
  if (col === 'next_milestone' && typeof v === 'object') {
    const m = v as { title?: string; due_on?: string | null };
    return m.due_on ? `${m.title} · ${m.due_on}` : (m.title ?? '—');
  }
  if (col === 'latest_update' && typeof v === 'object') return (v as { title?: string }).title ?? '—';
  if (Array.isArray(v)) return v.length ? `${v.length} people` : '—';
  if (typeof v === 'number') return v.toLocaleString();
  return String(v);
}

export function ProjectTable({
  data,
  columnNames,
  onOpenProject,
}: {
  data: QueryResult;
  /** labels of `field:<id>` columns (project fields) */
  columnNames: Record<string, string>;
  onOpenProject: (projectId: string) => void;
}) {
  const rows = data.rows ?? [];
  const cols = (data.columns ?? []).filter((c) => c !== 'name');
  if (!rows.length) return <Quiet>No projects here. {data.description}.</Quiet>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th scope="col" className="py-1 pr-3 font-medium">
              {COLUMN_LABELS.name}
            </th>
            {cols.map((c) => (
              <th key={c} scope="col" className="py-1 pr-3 font-medium whitespace-nowrap">
                {COLUMN_LABELS[c] ?? columnNames[c] ?? 'Field'}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r.id)} className="border-t border-hair-soft">
              <th scope="row" className="py-1.5 pr-3 text-left font-normal">
                <button
                  type="button"
                  onClick={() => onOpenProject(String(r.id))}
                  className="flex items-center gap-2 text-left hover:underline"
                >
                  <span
                    aria-hidden
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ background: tokenColor(r.color as string | null) ?? 'var(--muted-2)' }}
                  />
                  <span className="truncate">{String(r.name)}</span>
                </button>
              </th>
              {cols.map((c) => (
                <td key={c} className="py-1.5 pr-3 whitespace-nowrap tabular-nums text-ink-2">
                  {c === 'blocked' && r[c] ? (
                    <span className="flex items-center gap-1 text-crit">
                      <Icon icon={AlertTriangle} size={12} aria-hidden />
                      {String(r[c])}
                    </span>
                  ) : (
                    cellText(c, r[c])
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {data.more ? <p className="mt-2 text-xs text-muted">And {data.more} more.</p> : null}
    </div>
  );
}

// ---------- funnel, time in stage, aging ----------

export function Funnel({ data, onDrill }: { data: QueryResult; onDrill: (m: Mark) => void }) {
  const stages = data.stages ?? [];
  if (!stages.some((s) => s.count)) return <Quiet>No stage changes in this window yet.</Quiet>;
  const max = Math.max(1, ...stages.map((s) => s.count));
  return (
    <ol className="space-y-1">
      {stages.map((s) => (
        <li key={s.option_id}>
          <button
            type="button"
            className={BAR_BTN}
            onClick={() => onDrill({ key: s.option_id, label: s.label })}
          >
            <span className="flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate">{s.label}</span>
              <span className="tabular-nums text-muted">
                {s.count}
                {s.conversion !== null && s.conversion !== undefined
                  ? ` · ${Math.round(s.conversion * 100)}% of the stage before`
                  : ''}
              </span>
            </span>
            <span
              className="mx-auto mt-0.5 block h-3 rounded-sm bg-[var(--chart-1)]"
              style={{ width: `${Math.max(2, (s.count / max) * 100)}%` }}
            />
          </button>
        </li>
      ))}
    </ol>
  );
}

export function StageTime({ data, onDrill }: { data: QueryResult; onDrill: (m: Mark) => void }) {
  const stages = data.stages ?? [];
  if (!stages.some((s) => s.count)) return <Quiet>No one has left these stages in this window yet.</Quiet>;
  const max = Math.max(
    1,
    ...stages.flatMap((s) => [s.p90_days ?? 0, s.target_days ?? 0, s.median_days ?? 0]),
  );
  const pct = (v: number) => `${(v / max) * 100}%`;
  return (
    <ul className="space-y-2">
      {stages.map((s) => {
        const over =
          s.median_days !== null &&
          s.median_days !== undefined &&
          s.target_days &&
          s.median_days > s.target_days;
        return (
          <li key={s.option_id}>
            <button
              type="button"
              className={BAR_BTN}
              onClick={() => onDrill({ key: s.option_id, label: s.label })}
            >
              <span className="flex items-baseline justify-between gap-2 text-xs">
                <span className="truncate">{s.label}</span>
                <span className={cn('tabular-nums', over ? 'text-crit' : 'text-muted')}>
                  {s.median_days !== null && s.median_days !== undefined
                    ? `median ${s.median_days}d · p75 ${s.p75_days}d · p90 ${s.p90_days}d`
                    : 'no stays yet'}
                  {s.target_days ? ` · target ${s.target_days}d` : ''}
                </span>
              </span>
              <span className="relative mt-0.5 block h-3 rounded-sm bg-surface-2">
                {s.p90_days ? (
                  <span
                    aria-hidden
                    className="absolute inset-y-[5px] left-0 h-[2px] bg-[var(--muted-2)]"
                    style={{ width: pct(s.p90_days) }}
                  />
                ) : null}
                {s.median_days ? (
                  <span
                    aria-hidden
                    className={cn(
                      'absolute inset-y-0 left-0 rounded-sm',
                      over ? 'bg-[var(--crit)]' : 'bg-[var(--chart-1)]',
                    )}
                    style={{ width: pct(s.median_days) }}
                  />
                ) : null}
                {s.target_days ? (
                  <span
                    aria-hidden
                    className="absolute -inset-y-0.5 w-0.5 bg-ink"
                    style={{ left: pct(s.target_days) }}
                  />
                ) : null}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export const AGING_LABELS = ['0–7d', '8–14d', '15–30d', '31–60d', '60d+'];
const AGING_COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
];

export function Aging({ data, onDrill }: { data: QueryResult; onDrill: (m: Mark) => void }) {
  const stages = data.stages ?? [];
  if (!stages.some((s) => s.count)) return <Quiet>No projects in these stages right now.</Quiet>;
  const max = Math.max(1, ...stages.map((s) => s.count));
  return (
    <div>
      <ul className="space-y-1.5">
        {stages.map((s: StageStat) => (
          <li key={s.option_id}>
            <button
              type="button"
              className={BAR_BTN}
              onClick={() => onDrill({ key: s.option_id, label: s.label })}
            >
              <span className="flex items-baseline justify-between gap-2 text-xs">
                <span className="truncate">{s.label}</span>
                <span className="tabular-nums text-muted">
                  {s.count}
                  {s.breaches ? (
                    <span className="text-crit">
                      {' '}
                      · {s.breaches} past the {s.target_days}d target
                    </span>
                  ) : null}
                </span>
              </span>
              <span
                className="mt-0.5 flex h-3 overflow-hidden rounded-sm"
                style={{ width: `${Math.max(2, (s.count / max) * 100)}%` }}
              >
                {(s.buckets ?? []).map((n, i) =>
                  n ? (
                    <span
                      key={i}
                      aria-hidden
                      title={`${AGING_LABELS[i]}: ${n}`}
                      style={{ width: `${(n / s.count) * 100}%`, background: AGING_COLORS[i] }}
                    />
                  ) : null,
                )}
              </span>
              <span className="sr-only">
                {(s.buckets ?? []).map((n, i) => `${AGING_LABELS[i]}: ${n}`).join(', ')}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <ul className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted" aria-label="Days in stage">
        {AGING_LABELS.map((l, i) => (
          <li key={l} className="flex items-center gap-1.5">
            <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: AGING_COLORS[i] }} />
            {l}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------- timeline ----------

function weekOf(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y!, m! - 1, d!);
  const monday = new Date(date);
  monday.setDate(date.getDate() - ((date.getDay() + 6) % 7));
  return `Week of ${monday.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`;
}

const TIMELINE_KIND: Record<TimelineItem['kind'], string> = {
  milestone: 'Milestone',
  go_live: 'Date',
  target: 'Target',
};

export function Timeline({
  data,
  onOpenProject,
}: {
  data: QueryResult;
  onOpenProject: (projectId: string) => void;
}) {
  const items = data.timeline ?? [];
  if (!items.length) return <Quiet>Nothing dated in this window.</Quiet>;
  const weeks = new Map<string, TimelineItem[]>();
  for (const i of items) {
    const w = weekOf(i.date);
    weeks.set(w, [...(weeks.get(w) ?? []), i]);
  }
  return (
    <div className="max-h-80 space-y-3 overflow-auto">
      {[...weeks.entries()].map(([week, list]) => (
        <section key={week} aria-label={week}>
          <h4 className="text-xs font-medium text-muted">{week}</h4>
          <ul className="mt-1 divide-y divide-hair-soft">
            {list.map((i) => (
              <li key={`${i.project_id}-${i.kind}-${i.date}-${i.title}`}>
                <button
                  type="button"
                  onClick={() => onOpenProject(i.project_id)}
                  className="flex w-full items-baseline gap-3 rounded-md px-1 py-1.5 text-left text-sm hover:bg-surface-2"
                >
                  <span className="w-14 shrink-0 text-xs tabular-nums text-muted">{i.date.slice(5)}</span>
                  <span className="min-w-0 flex-1 truncate">{i.project_name}</span>
                  <span className="shrink-0 truncate text-xs text-muted">
                    {TIMELINE_KIND[i.kind]}: {i.title}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

// ---------- note ----------

/** Markdown-ish text shown as text: paragraphs and line breaks, never HTML. */
export function Note({ text }: { text: string }) {
  return (
    <div className="space-y-2 text-sm text-ink-2">
      {text.split(/\n{2,}/).map((p, i) => (
        <p key={i} className="whitespace-pre-line">
          {p}
        </p>
      ))}
    </div>
  );
}
