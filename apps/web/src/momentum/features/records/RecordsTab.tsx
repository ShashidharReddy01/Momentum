import { Download, FileStack, Search } from 'lucide-react';
import { lazy, Suspense, useDeferredValue, useState } from 'react';
import { Link } from 'react-router';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { Segmented } from '@/components/ui/Tabs';
import { useUndoToast } from '@/lib/undo';
import { getPath, humanize, type Display } from './model';
import {
  useBulkStatus,
  useEntities,
  useRecords,
  useRecordTotals,
  useRecordTypes,
  type RecordFilters,
} from './queries';
import { RECORD_STATUS, RecordStatus } from './RecordStatus';

const ReportDialog = lazy(() => import('@/features/reports').then((m) => ({ default: m.ReportDialog })));

function cell(v: unknown): string {
  if (v == null || v === '') return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/**
 * The project's Records tab (Phase 7.6 S76-08, spec §12.5): one record type at a time, a table
 * from the type's `columns`, filters (status, date range, words), totals per currency from the
 * server, export, and for editors "Send to review" / "Void" on the selected rows (one undo).
 */
export function RecordsTab({
  projectId,
  projectName,
  canEdit,
}: {
  projectId: string;
  projectName: string;
  canEdit: boolean;
}) {
  const types = useRecordTypes(projectId);
  const withRecords = (types.data ?? []).filter((t) => t.count > 0);
  const [typeKey, setTypeKey] = useState<string | null>(null);
  const type = withRecords.find((t) => t.key === typeKey) ?? withRecords[0];
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [entityId, setEntityId] = useState('');
  const entities = useEntities('', null);
  const deferredQ = useDeferredValue(q.trim());
  const filters: RecordFilters = {
    type: type?.key,
    status: status ? [status] : [],
    entity_id: entityId || undefined,
    q: deferredQ,
    from,
    to,
  };
  const records = useRecords(projectId, filters, !!type);
  const totals = useRecordTotals(projectId, { ...filters, q: undefined }, !!type);
  const bulk = useBulkStatus();
  const undoToast = useUndoToast();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);

  if (types.isPending) return <Skeleton className="h-64" />;
  if (types.isError) return <ErrorState error={types.error} onRetry={() => void types.refetch()} />;
  if (!type)
    return (
      <EmptyState icon={FileStack} title="No records yet">
        Records are what agents read from your documents (invoices, for example). They show up here once an
        agent makes one in this project.
      </EmptyState>
    );
  const display = type.display as Display;
  const columns = display.columns?.length ? display.columns : ['title'];
  const rows = records.data ?? [];
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const sel = 'rounded-md border border-hairline bg-surface px-2 py-1 text-sm text-ink';

  const act = (next: 'needs_review' | 'void') =>
    bulk.mutate(
      { ids: [...selected], status: next },
      {
        onSuccess: (r) => {
          setSelected(new Set());
          const word = next === 'void' ? 'Voided' : 'Sent to review';
          undoToast(
            `${word} ${r.updated} record${r.updated === 1 ? '' : 's'}${r.skipped.length ? ` (${r.skipped.length} left as they were)` : ''}`,
            { batch_id: r.batch_id },
          );
        },
      },
    );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {withRecords.length > 1 ? (
          <Segmented
            label="Record type"
            value={type.key}
            onChange={(v) => {
              setTypeKey(v);
              setSelected(new Set());
            }}
            options={withRecords.map((t) => ({ value: t.key, label: `${t.label} (${t.count})` }))}
          />
        ) : (
          <h2 className="text-sm font-semibold">
            {type.label} <span className="font-normal text-muted">({type.count})</span>
          </h2>
        )}
        <span className="flex-1" />
        <Button size="sm" variant="text" onClick={() => setExporting(true)}>
          <Icon icon={Download} size={14} /> Export
        </Button>
      </div>
      <div role="search" aria-label="Filter records" className="flex flex-wrap items-center gap-2">
        <label className="relative flex min-w-48 flex-1 items-center">
          <Icon icon={Search} size={14} className="pointer-events-none absolute left-2 text-muted" />
          <span className="sr-only">Search records</span>
          <input
            type="search"
            placeholder="Search…"
            className="h-8 w-full rounded-md border border-hairline bg-surface pr-2 pl-7 text-sm"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-1 text-xs text-muted">
          Status
          <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any</option>
            {Object.entries(RECORD_STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
        </label>
        {entities.data?.length ? (
          <label className="flex items-center gap-1 text-xs text-muted">
            Linked to
            <select className={sel} value={entityId} onChange={(e) => setEntityId(e.target.value)}>
              <option value="">Anyone</option>
              {entities.data.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="flex items-center gap-1 text-xs text-muted">
          From
          <input type="date" className={sel} value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="flex items-center gap-1 text-xs text-muted">
          To
          <input type="date" className={sel} value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>

      <Totals result={totals.data} />

      {canEdit && selected.size ? (
        <div role="toolbar" aria-label="Selected records" className="flex items-center gap-2 text-sm">
          <span className="text-muted">{selected.size} selected</span>
          <Button size="sm" disabled={bulk.isPending} onClick={() => act('needs_review')}>
            Send to review
          </Button>
          <Button size="sm" disabled={bulk.isPending} onClick={() => act('void')}>
            Void
          </Button>
        </div>
      ) : null}

      {records.isError ? (
        <ErrorState error={records.error} onRetry={() => void records.refetch()} />
      ) : (
        <div className="overflow-x-auto rounded-md border border-hairline">
          <table className="w-full text-sm" aria-label={`${type.label} records`}>
            <thead>
              <tr className="bg-surface-2 text-left text-xs text-muted">
                {canEdit ? (
                  <th scope="col" className="w-8 px-2 py-1.5">
                    <input
                      type="checkbox"
                      aria-label="Select all"
                      checked={allSelected}
                      onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.id)))}
                    />
                  </th>
                ) : null}
                {columns.map((c) => (
                  <th key={c} scope="col" className="px-2 py-1.5 font-normal">
                    {humanize(c)}
                  </th>
                ))}
                <th scope="col" className="px-2 py-1.5 font-normal">
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-hair-soft hover:bg-surface-2">
                  {canEdit ? (
                    <td className="px-2">
                      <input
                        type="checkbox"
                        aria-label={`Select ${r.title}`}
                        checked={selected.has(r.id)}
                        onChange={() =>
                          setSelected((s) => {
                            const n = new Set(s);
                            if (n.has(r.id)) n.delete(r.id);
                            else n.add(r.id);
                            return n;
                          })
                        }
                      />
                    </td>
                  ) : null}
                  {columns.map((c, i) => (
                    <td key={c} className="px-2 py-1.5">
                      {i === 0 ? (
                        <Link to={`/records/${r.id}`} className="font-medium text-accent hover:underline">
                          {cell(getPath(r.data, c))}
                        </Link>
                      ) : (
                        cell(getPath(r.data, c))
                      )}
                    </td>
                  ))}
                  <td className="px-2 py-1.5">
                    <RecordStatus status={r.status} />
                  </td>
                </tr>
              ))}
              {!rows.length && !records.isPending ? (
                <tr>
                  <td colSpan={columns.length + 2} className="px-2 py-6 text-center text-sm text-muted">
                    No records match.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
      {exporting ? (
        <Suspense fallback={null}>
          <ReportDialog
            open
            onOpenChange={setExporting}
            scope={{ projectId }}
            name={projectName}
            initialKind="records_export"
          />
        </Suspense>
      ) : null}
    </div>
  );
}

function Totals({
  result,
}: {
  result?: { rows: { currency?: string | null; values: Record<string, number | null> }[] };
}) {
  if (!result?.rows.length) return null;
  return (
    <p aria-label="Totals" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {result.rows.map((r, i) => (
        <span key={r.currency ?? i}>
          <span className="font-semibold tabular-nums">
            {r.values['sum(amount)'] == null
              ? '—'
              : r.values['sum(amount)'].toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
          </span>{' '}
          <span className="text-muted">
            {r.currency ?? 'no currency'} · {r.values.count ?? 0} record{r.values.count === 1 ? '' : 's'}
          </span>
        </span>
      ))}
      <span className="text-xs text-muted">Totals are per currency and never added across currencies.</span>
    </p>
  );
}
