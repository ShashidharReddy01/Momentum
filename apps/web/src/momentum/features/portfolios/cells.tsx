import { Diamond } from 'lucide-react';
import { Link } from 'react-router';
import { Avatar } from '@/components/ui/Avatar';
import { Icon } from '@/components/ui/Icon';
import { FieldValueChip, FieldValueEditor, type Field } from '@/features/fields';
import { StatusChip, type Status } from '@/features/status';
import { cn } from '@/lib/cn';
import { formatRelative, fromISODate } from '@/lib/dates';
import type { ColumnV2, RowV2 } from './v2queries';

const DAY = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
const MONEY = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

export const day = (iso: string | null | undefined) => (iso ? DAY.format(fromISODate(iso)) : null);
export const money = (n: number, unit?: string | null) => `${MONEY.format(n)}${unit ? ` ${unit}` : ''}`;

/** Numeric columns line up right (tabular figures). */
export const NUMERIC_KEYS = new Set([
  'open',
  'overdue',
  'blocked',
  'waiting_on_customer',
  'slip_days',
  'stage_age_days',
  'progress',
]);

export function fieldOf(key: string, fields: Map<string, Field>): Field | undefined {
  return key.startsWith('field:') ? fields.get(key.slice('field:'.length)) : undefined;
}

export function columnLabel(c: ColumnV2): string {
  return c.label;
}

const Empty = () => <span className="text-muted-2">—</span>;

/** One table cell. Built-ins come from the server already computed; project fields are editable
 * in place when the viewer may edit that project (`row.can_edit`). */
export function Cell({
  col,
  row,
  fields,
  onEdit,
}: {
  col: ColumnV2;
  row: RowV2;
  fields: Map<string, Field>;
  onEdit: (field: Field, value: unknown) => void;
}) {
  const f = fieldOf(col.key, fields);
  if (f) {
    const value = row.fields[f.id] ?? null;
    if (row.can_edit)
      return (
        <div className="min-w-0" data-cell-editor>
          <FieldValueEditor field={f} value={value} onChange={(v) => onEdit(f, v)} />
        </div>
      );
    return value === null ? <Empty /> : <FieldValueChip field={f} value={value} />;
  }
  switch (col.key) {
    case 'name':
      return (
        <span className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden
            className="h-2.5 w-2.5 shrink-0 rounded-sm"
            style={{ background: `var(--${row.color ?? 'hairline'})` }}
          />
          <Link to={`/projects/${row.id}/overview`} className="truncate font-medium hover:underline">
            {row.name}
          </Link>
        </span>
      );
    case 'owner':
      return row.owner_name ? (
        <span className="flex min-w-0 items-center gap-1.5">
          <Avatar name={row.owner_name} size={20} />
          <span className="truncate">{row.owner_name}</span>
        </span>
      ) : (
        <Empty />
      );
    case 'status':
      return row.status ? <StatusChip status={row.status as Status} /> : <Empty />;
    case 'stage':
      return row.stage ? <StageChip label={row.stage.label ?? row.stage.option_id} /> : <Empty />;
    case 'progress':
      return row.progress === null || row.progress === undefined ? (
        <Empty />
      ) : (
        <span
          className="flex items-center gap-2"
          title={`${row.completed_tasks} of ${row.total_tasks} tasks done`}
        >
          <span className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-2" aria-hidden>
            <span className="block h-full bg-ok" style={{ width: `${Math.round(row.progress * 100)}%` }} />
          </span>
          <span className="tabular-nums">{Math.round(row.progress * 100)}%</span>
        </span>
      );
    case 'open':
      return <span className="tabular-nums">{row.open}</span>;
    case 'overdue':
      return <span className={cn('tabular-nums', row.overdue > 0 && 'text-crit')}>{row.overdue}</span>;
    case 'blocked':
      return <span className={cn('tabular-nums', row.blocked > 0 && 'text-warn')}>{row.blocked}</span>;
    case 'waiting_on_customer':
      return row.waiting_on_customer === null || row.waiting_on_customer === undefined ? (
        <span className="text-muted-2" title="No “Waiting on” task field in this workspace">
          —
        </span>
      ) : (
        <span className="tabular-nums">{row.waiting_on_customer}</span>
      );
    case 'next_milestone':
      return row.next_milestone ? (
        <span className="flex min-w-0 items-center gap-1">
          <Icon icon={Diamond} size={12} className="shrink-0 text-muted" />
          <span className="truncate">{row.next_milestone.title}</span>
          {row.next_milestone.due_on ? (
            <span className="shrink-0 text-xs text-muted">{day(row.next_milestone.due_on)}</span>
          ) : null}
        </span>
      ) : (
        <Empty />
      );
    case 'target_date':
      return row.target_date ? <span className="tabular-nums">{day(row.target_date)}</span> : <Empty />;
    case 'forecast_date':
      return row.forecast_date ? <span className="tabular-nums">{day(row.forecast_date)}</span> : <Empty />;
    case 'slip_days':
      return row.slip_days === null || row.slip_days === undefined ? (
        <Empty />
      ) : (
        <span className={cn('tabular-nums', row.slip_days > 0 ? 'text-crit' : 'text-ok')}>
          {row.slip_days > 0 ? `+${row.slip_days}` : row.slip_days}
        </span>
      );
    case 'stage_age_days':
      return row.stage_age_days === null || row.stage_age_days === undefined ? (
        <Empty />
      ) : (
        <span
          className={cn(
            'tabular-nums',
            row.stage_target_days !== null &&
              row.stage_target_days !== undefined &&
              row.stage_age_days > row.stage_target_days &&
              'text-crit',
          )}
          title={row.stage_target_days ? `Target ${row.stage_target_days} days` : undefined}
        >
          {row.stage_age_days}
        </span>
      );
    case 'latest_update':
      return row.latest_update ? (
        <span className="flex min-w-0 items-center gap-1.5">
          <StatusChip status={row.latest_update.status as Status} />
          <span className="truncate" title={row.latest_update.title}>
            {row.latest_update.title}
          </span>
          <span className="shrink-0 text-xs text-muted">{formatRelative(row.latest_update.at)}</span>
        </span>
      ) : (
        <Empty />
      );
    default:
      return <Empty />;
  }
}

/** A stage, as a quiet pill: stages are a sequence, not a health signal, so no color. */
export function StageChip({ label }: { label: string }) {
  return (
    <span className="inline-flex max-w-full items-center rounded-full border border-hairline px-2 py-0.5 text-xs">
      <span className="truncate">{label}</span>
    </span>
  );
}
