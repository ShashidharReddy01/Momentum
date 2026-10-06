import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { EmptyState } from '@/components/common/States';
import { Segmented } from '@/components/ui/Tabs';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { addDays, dayDiff, fromISODate, toISODate } from '@/lib/dates';
import { day } from './cells';
import type { PortfolioDetail } from './queries';
import { usePortfolioRows, type RowV2 } from './v2queries';

type Zoom = 'month' | 'quarter';
type GroupBy = 'stage' | 'owner';
const PX_PER_DAY: Record<Zoom, number> = { month: 8, quarter: 2.5 };
const LABEL_WIDTH = 220;
const MONTH = new Intl.DateTimeFormat(undefined, { month: 'short', year: '2-digit' });

/**
 * Portfolio timeline (spec §5.4): one bar per project from its start to its target date, the
 * forecast cone past the target when it is late (red) or the slack before it (green), the next
 * milestone as a diamond and a line for today. Grouped by stage or owner; zoom by month or
 * quarter. A project without a start shows only its target; one without dates says so.
 */
export function PortfolioTimeline({ p }: { p: PortfolioDetail }) {
  const [zoom, setZoom] = useState<Zoom>('month');
  const [groupBy, setGroupBy] = useState<GroupBy>(p.stage_field_id ? 'stage' : 'owner');
  const q = usePortfolioRows(p.id, { groupBy });
  const today = toISODate(new Date());

  const range = useMemo(() => {
    const dates = (q.data?.rows ?? []).flatMap((r) =>
      [r.start_on, r.target_date, r.forecast_date, r.next_milestone?.due_on].filter((d): d is string => !!d),
    );
    if (!dates.length) return null;
    const sorted = [...dates, today].sort();
    return {
      start: addDays(fromISODate(sorted[0]!), -7),
      end: addDays(fromISODate(sorted[sorted.length - 1]!), 14),
    };
  }, [q.data, today]);

  if (q.isPending) return <Skeleton className="h-64" />;
  if (q.isError) return <p className="text-sm text-crit">Couldn’t load the timeline.</p>;
  if (!range)
    return (
      <EmptyState title="No dates to place yet">
        Projects appear here once they have a start, a due date or a stage target.
      </EmptyState>
    );

  const px = PX_PER_DAY[zoom];
  const total = dayDiff(range.start, range.end);
  const x = (iso: string) => dayDiff(range.start, fromISODate(iso)) * px;
  const byId = new Map(q.data.rows.map((r) => [r.id, r]));
  const months: { iso: string; label: string }[] = [];
  for (
    let d = new Date(range.start.getFullYear(), range.start.getMonth(), 1);
    d <= range.end;
    d = new Date(d.getFullYear(), d.getMonth() + 1, 1)
  )
    months.push({ iso: toISODate(d), label: MONTH.format(d) });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented<GroupBy>
          label="Group by"
          value={groupBy}
          onChange={setGroupBy}
          options={[
            ...(p.stage_field_id ? [{ value: 'stage' as const, label: 'Stage' }] : []),
            { value: 'owner', label: 'Owner' },
          ]}
        />
        <Segmented<Zoom>
          label="Zoom"
          value={zoom}
          onChange={setZoom}
          options={[
            { value: 'month', label: 'Month' },
            { value: 'quarter', label: 'Quarter' },
          ]}
        />
        <span className="flex items-center gap-3 text-xs text-muted" aria-hidden>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-4 rounded-sm bg-accent/70" /> plan
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-4 rounded-sm bg-crit/40" /> forecast past target
          </span>
        </span>
      </div>
      <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
        <div style={{ width: LABEL_WIDTH + total * px }} className="relative">
          <div className="sticky top-0 z-10 flex border-b border-hairline bg-surface text-xs text-muted">
            <div style={{ width: LABEL_WIDTH }} className="sticky left-0 shrink-0 bg-surface px-3 py-1.5">
              Project
            </div>
            <div className="relative h-7 flex-1">
              {months.map((m) => (
                <span
                  key={m.iso}
                  className="absolute top-1.5 border-l border-hair-soft pl-1"
                  style={{ left: Math.max(0, x(m.iso)) }}
                >
                  {m.label}
                </span>
              ))}
            </div>
          </div>
          <div
            aria-hidden
            className="absolute bottom-0 top-0 z-[5] w-px bg-crit/60"
            style={{ left: LABEL_WIDTH + x(today) }}
            title="Today"
          />
          <section aria-label={`Timeline of ${p.name}`}>
            {(q.data.groups ?? []).map((g) => {
              const rows = g.project_ids.map((id) => byId.get(id)).filter((r): r is RowV2 => !!r);
              if (!rows.length) return null;
              return (
                <div key={g.key ?? 'none'}>
                  <div
                    className="sticky left-0 bg-surface-2 px-3 py-1 text-xs font-semibold"
                    style={{ width: LABEL_WIDTH + total * px }}
                  >
                    {g.label} <span className="font-normal text-muted">{rows.length}</span>
                  </div>
                  <div role="list" aria-label={g.label}>
                    {rows.map((r) => (
                      <Bar key={r.id} r={r} x={x} />
                    ))}
                  </div>
                </div>
              );
            })}
          </section>
        </div>
      </div>
    </div>
  );
}

function Bar({ r, x }: { r: RowV2; x: (iso: string) => number }) {
  const start = r.start_on ? x(r.start_on) : null;
  const end = r.target_date ? x(r.target_date) : null;
  const forecast = r.forecast_date ? x(r.forecast_date) : null;
  const late = (r.slip_days ?? 0) > 0;
  const label = [
    r.name,
    r.start_on ? `starts ${day(r.start_on)}` : null,
    r.target_date ? `target ${day(r.target_date)}` : 'no target date',
    r.forecast_date ? `forecast ${day(r.forecast_date)}` : null,
    r.slip_days ? `${r.slip_days > 0 ? `${r.slip_days} days late` : `${-r.slip_days} days early`}` : null,
  ]
    .filter(Boolean)
    .join(', ');
  return (
    <div role="listitem" aria-label={label} className="flex h-9 items-center border-b border-hair-soft">
      <div
        style={{ width: LABEL_WIDTH }}
        className="sticky left-0 z-[6] shrink-0 truncate bg-surface px-3 text-sm"
      >
        <Link to={`/projects/${r.id}/overview`} className="hover:underline">
          {r.name}
        </Link>
      </div>
      <div className="relative h-full flex-1">
        {start !== null && end !== null && end > start ? (
          <span
            className="absolute top-3 h-3 rounded-sm bg-accent/70"
            style={{ left: start, width: end - start }}
          />
        ) : end !== null ? (
          <span className="absolute top-3 h-3 w-1 rounded-sm bg-accent/70" style={{ left: end }} />
        ) : null}
        {end !== null && forecast !== null && forecast !== end ? (
          <span
            className={cn('absolute top-2.5 h-4 rounded-sm', late ? 'bg-crit/40' : 'bg-ok/30')}
            style={{ left: Math.min(end, forecast), width: Math.abs(forecast - end) }}
          />
        ) : null}
        {r.next_milestone?.due_on ? (
          <span
            className="absolute top-2.5 h-3 w-3 rotate-45 border border-ink bg-surface"
            style={{ left: x(r.next_milestone.due_on) - 6 }}
            title={`${r.next_milestone.title} ${day(r.next_milestone.due_on)}`}
          />
        ) : null}
      </div>
    </div>
  );
}
